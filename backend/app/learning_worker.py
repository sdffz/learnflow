from __future__ import annotations

import hashlib
import logging
import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import uuid4
from zipfile import ZipFile

from .chaoxing_adapter import MAX_IMPORT_FILE_BYTES, ChaoxingAdapterError
from .ingestion import (
    IMAGE_FORMATS,
    SUPPORTED_EXTENSIONS,
    TextExtraction,
    extract_text,
    inspect_uploaded_file,
)
from .learning_domain import ImportJob, ImportJobItem
from .learning_service import PREVIEW_TTL, LearningService
from .zip_import import safe_zip_member

logger = logging.getLogger("learnflow.learning_worker")


def _suffix_for_item(item: ImportJobItem) -> str:
    candidates = [item.title]
    if item.source_url:
        candidates.append(unquote(urlparse(item.source_url).path.rsplit("/", 1)[-1]))
    for value in candidates:
        suffix = Path(value).suffix.casefold()
        if suffix:
            return suffix
    raise ValueError("unsupported_file_type")


class LearningWorker:
    def __init__(
        self,
        service: LearningService,
        *,
        runtime_dir: Path,
    ):
        self.service = service
        self.runtime_dir = runtime_dir
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.service.learning_store.recover_interrupted_jobs()
        self.cleanup_expired_archives()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="learnflow-learning-worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def wake(self) -> None:
        self._wake.set()

    def cleanup_expired_archives(self) -> int:
        removed = 0
        for row in self.service.learning_store.list_expired_zip_archives():
            self._cleanup_archive(
                knowledge_store=self.service.knowledge_store,
                archive_relpath=row["archive_relpath"],
            )
            removed += 1
        zip_root = self.service.knowledge_store.upload_dir / "tmp" / "zip"
        if zip_root.is_dir():
            boundary = (
                datetime.now(UTC).timestamp() - PREVIEW_TTL.total_seconds()
            )
            for path in zip_root.rglob("*.zip"):
                try:
                    if path.is_file() and path.stat().st_mtime < boundary:
                        path.unlink(missing_ok=True)
                        removed += 1
                except OSError:
                    continue
        return removed

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(timeout=5)
            self._wake.clear()
            if self._stop.is_set():
                break
            try:
                self.service.sweep_expired_logins()
                self.cleanup_expired_archives()
                self.run_once()
            except Exception:
                logger.exception("learning_worker_tick_failed")

    def run_once(self, *, job_id: str | None = None) -> list[str]:
        processed: list[str] = []
        for scoped in self.service.learning_store.list_runnable_jobs():
            if job_id is not None and scoped.job.id != job_id:
                continue
            result = self.run_job(
                scoped.workspace_id,
                scoped.user_id,
                scoped.job.id,
            )
            if result is not None:
                processed.append(result.id)
        return processed

    def run_job(
        self,
        workspace_id: str,
        user_id: str,
        job_id: str,
    ) -> ImportJob | None:
        store = self.service.learning_store
        job = store.get_job(workspace_id, user_id, job_id)
        if job is None or job.status != "queued":
            return job
        cursor = store.claim_job(workspace_id, user_id, job_id)
        if cursor is None:
            return store.get_job(workspace_id, user_id, job_id)
        preview = store.get_preview(workspace_id, user_id, job.preview_id)
        if preview is None:
            self._cleanup_job_temp(workspace_id, job_id)
            self._cleanup_archive(
                knowledge_store=self.service.knowledge_store,
                archive_relpath=store.get_preview_archive_relpath(
                    workspace_id,
                    user_id,
                    job.preview_id,
                ),
            )
            return store.update_job(
                workspace_id=workspace_id,
                user_id=user_id,
                job_id=job_id,
                status="partial_failed",
                finished_at=datetime.now(UTC).isoformat(),
                error_code="preview_expired",
                error_message="导入预览已过期，请重新生成预览。",
            )
        connection = store.load_connection(workspace_id, user_id)
        if not preview.archive_relpath and (
            connection is None
            or connection.status != "connected"
            or not connection.cookies
        ):
            self._cleanup_job_temp(workspace_id, job_id)
            return store.update_job(
                workspace_id=workspace_id,
                user_id=user_id,
                job_id=job_id,
                status="session_expired",
                finished_at=datetime.now(UTC).isoformat(),
                error_code="session_expired",
                error_message="请重新扫码连接学习通后重试。",
            )
        preview_courses = {course.id: course for course in preview.courses}
        cookies = connection.cookies if connection and connection.cookies else {}
        for item in store.list_job_items(workspace_id, user_id, job_id):
            current = store.get_job(workspace_id, user_id, job_id)
            if current is None:
                return None
            if current.status in {"cancelled", "session_expired"}:
                archive_relpath = store.get_preview_archive_relpath(
                    workspace_id,
                    user_id,
                    current.preview_id,
                )
                if current.status == "cancelled":
                    self._cleanup_archive(
                        knowledge_store=self.service.knowledge_store,
                        archive_relpath=archive_relpath,
                    )
                return current
            if item.status != "queued":
                continue
            try:
                if item.kind in {"file", "zip_file"}:
                    item_cookies = cookies
                    if item.kind == "file" and not preview.archive_relpath:
                        refreshed_connection = store.load_connection(
                            workspace_id,
                            user_id,
                        )
                        if (
                            refreshed_connection is None
                            or refreshed_connection.status != "connected"
                            or not refreshed_connection.cookies
                        ):
                            return self._finish_job(
                                workspace_id,
                                user_id,
                                job_id,
                                forced_status="session_expired",
                                error_code="session_expired",
                            )
                        item_cookies = refreshed_connection.cookies
                    archive_relpath = preview.archive_relpath
                    self._import_file(
                        workspace_id,
                        user_id,
                        item_cookies,
                        job_id,
                        item,
                        archive_path=(
                            self.service.knowledge_store.upload_dir
                            / archive_relpath
                            if archive_relpath
                            else None
                        ),
                    )
                else:
                    store.update_job(
                        workspace_id=workspace_id,
                        user_id=user_id,
                        job_id=job_id,
                        status="parsing",
                    )
                    course = preview_courses.get(item.external_course_id)
                    if course is None:
                        raise ChaoxingAdapterError("upstream_changed")
                    content = "\n".join(
                        [
                            f"# {course.title} · 视频资料链接",
                            "",
                            "以下视频未下载，仅保留学习通原链接。",
                            "",
                            *[f"- [{link}]({link})" for link in course.video_links],
                        ]
                    )
                    _asset, created = self.service.knowledge_store.upsert_external_note(
                        course_id=item.target_course_id,
                        workspace_id=workspace_id,
                        external_source="chaoxing",
                        external_id=f"video-links:{course.id}",
                        title=f"{course.title} · 视频资料链接",
                        content=content,
                        tags=["学习通", "视频资料"],
                    )
                    store.update_job_item(
                        workspace_id=workspace_id,
                        user_id=user_id,
                        job_id=job_id,
                        item_id=item.id,
                        status="completed" if created else "skipped",
                        attempts=item.attempts + 1,
                    )
            except ChaoxingAdapterError as exc:
                store.update_job_item(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    job_id=job_id,
                    item_id=item.id,
                    status="failed",
                    attempts=item.attempts + 1,
                    error_code=exc.code,
                    error_message=self._message_for(exc.code),
                )
                if exc.code == "session_expired":
                    return self._finish_job(
                        workspace_id,
                        user_id,
                        job_id,
                        forced_status="session_expired",
                        error_code=exc.code,
                    )
            except Exception as exc:
                logger.exception(
                    "learning_item_failed job_id=%s item_id=%s",
                    job_id,
                    item.id,
                )
                store.update_job_item(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    job_id=job_id,
                    item_id=item.id,
                    status="failed",
                    attempts=item.attempts + 1,
                    error_code="import_failed",
                    error_message=str(exc)[:240] or "资料导入失败",
                )
            self._refresh_progress(workspace_id, user_id, job_id)
        return self._finish_job(workspace_id, user_id, job_id)

    def _import_file(
        self,
        workspace_id: str,
        user_id: str,
        cookies: dict[str, str],
        job_id: str,
        item: ImportJobItem,
        *,
        archive_path: Path | None,
    ) -> None:
        store = self.service.learning_store
        knowledge_store = self.service.knowledge_store
        if item.kind == "file" and not item.source_url:
            raise ChaoxingAdapterError("upstream_changed")
        suffix = _suffix_for_item(item)
        if suffix not in SUPPORTED_EXTENSIONS:
            store.update_job_item(
                workspace_id=workspace_id,
                user_id=user_id,
                job_id=job_id,
                item_id=item.id,
                status="skipped",
                error_code="unsupported_file_type",
            )
            return
        if item.size_bytes > MAX_IMPORT_FILE_BYTES:
            raise ChaoxingAdapterError("file_too_large")
        temporary = (
            knowledge_store.upload_dir
            / "tmp"
            / workspace_id
            / job_id
            / f"{item.id}{suffix}"
        )
        final: Path | None = None
        try:
            store.update_job(
                workspace_id=workspace_id,
                user_id=user_id,
                job_id=job_id,
                status="downloading",
            )
            if item.kind == "zip_file":
                checksum = self._extract_zip_member(
                    archive_path,
                    item,
                    temporary,
                )
            else:
                checksum = self.service.adapter.download(
                    cookies,
                    item.source_url or "",
                    temporary,
                    expected_size=item.size_bytes,
                )
            size = temporary.stat().st_size
            if size > MAX_IMPORT_FILE_BYTES:
                raise ChaoxingAdapterError("file_too_large")
            store.update_job(
                workspace_id=workspace_id,
                user_id=user_id,
                job_id=job_id,
                status="parsing",
            )
            try:
                mime_type = inspect_uploaded_file(temporary, suffix)
            except ValueError as exc:
                raise ChaoxingAdapterError(str(exc)) from exc
            try:
                extraction = extract_text(temporary, mime_type)
            except Exception as exc:
                extraction = TextExtraction(
                    text="",
                    status="failed",
                    error=f"extract_failed: {exc}",
                )
            relative = (
                Path(workspace_id)
                / item.target_course_id
                / f"{uuid4().hex}{suffix}"
            )
            final = knowledge_store.upload_dir / relative
            final.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(temporary), final)
            _asset, created = knowledge_store.upsert_external_asset(
                course_id=item.target_course_id,
                workspace_id=workspace_id,
                external_source="chaoxing",
                external_id=item.external_file_id or item.id,
                source_url=item.source_url or f"zip:{item.archive_member}",
                checksum=checksum,
                title=Path(item.title).stem or item.title,
                original_name=Path(item.title).name,
                mime_type=mime_type,
                file_relpath=str(relative),
                extraction=extraction,
                tags=["学习通", "课程资料"],
                size_bytes=size,
                kind="image" if suffix in IMAGE_FORMATS else "file",
            )
            store.update_job_item(
                workspace_id=workspace_id,
                user_id=user_id,
                job_id=job_id,
                item_id=item.id,
                status="completed" if created else "skipped",
                attempts=item.attempts + 1,
                checksum=checksum,
                asset_id=_asset.id,
            )
        except Exception:
            if final is not None:
                final.unlink(missing_ok=True)
            raise
        finally:
            temporary.unlink(missing_ok=True)

    def _extract_zip_member(
        self,
        archive_path: Path | None,
        item: ImportJobItem,
        destination: Path,
    ) -> str:
        if archive_path is None or not item.archive_member:
            raise ChaoxingAdapterError("preview_expired")
        member = str(safe_zip_member(item.archive_member))
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with ZipFile(archive_path) as archive:
                info = archive.getinfo(member)
                if info.file_size > MAX_IMPORT_FILE_BYTES:
                    raise ChaoxingAdapterError("file_too_large")
                digest = hashlib.sha256()
                size = 0
                with archive.open(info) as source, destination.open("wb") as target:
                    while chunk := source.read(64 * 1024):
                        size += len(chunk)
                        if size > MAX_IMPORT_FILE_BYTES:
                            raise ChaoxingAdapterError("file_too_large")
                        digest.update(chunk)
                        target.write(chunk)
                return digest.hexdigest()
        except KeyError as exc:
            raise ChaoxingAdapterError("invalid_file_content") from exc

    def _refresh_progress(
        self,
        workspace_id: str,
        user_id: str,
        job_id: str,
    ) -> ImportJob | None:
        store = self.service.learning_store
        job = store.get_job(workspace_id, user_id, job_id)
        if job is None:
            return None
        items = store.list_job_items(workspace_id, user_id, job_id)
        completed = sum(item.status == "completed" for item in items)
        skipped = sum(item.status == "skipped" for item in items)
        failed = sum(item.status == "failed" for item in items)
        processed = completed + skipped + failed
        progress = int(round(processed / len(items) * 100)) if items else 0
        return store.update_job(
            workspace_id=workspace_id,
            user_id=user_id,
            job_id=job_id,
            progress=min(progress, 100),
            completed_items=completed,
            skipped_items=skipped,
            failed_items=failed,
        )

    def _finish_job(
        self,
        workspace_id: str,
        user_id: str,
        job_id: str,
        *,
        forced_status: str | None = None,
        error_code: str | None = None,
    ) -> ImportJob | None:
        store = self.service.learning_store
        refreshed = self._refresh_progress(workspace_id, user_id, job_id)
        if refreshed is None:
            return None
        self._cleanup_job_temp(workspace_id, job_id)
        status = forced_status or (
            "partial_failed" if refreshed.failed_items else "completed"
        )
        final = store.update_job(
            workspace_id=workspace_id,
            user_id=user_id,
            job_id=job_id,
            status=status,
            progress=100,
            finished_at=datetime.now(UTC).isoformat(),
            error_code=error_code,
            error_message=(
                "部分资料导入失败，可重试失败项。"
                if status == "partial_failed"
                else self._message_for(error_code) if error_code else None
            ),
        )
        if final is not None and final.status in {"completed", "cancelled"}:
            self._cleanup_archive(
                knowledge_store=self.service.knowledge_store,
                archive_relpath=store.get_preview_archive_relpath(
                    workspace_id,
                    user_id,
                    final.preview_id,
                ),
            )
        return final

    @staticmethod
    def _cleanup_archive(
        *,
        knowledge_store,
        archive_relpath: str | None,
    ) -> None:
        if not archive_relpath:
            return
        # The temporary ZIP is removed only after a terminal outcome. Partial
        # failures retain it so the failed members can be retried.
        root = knowledge_store.upload_dir.resolve()
        preview_path = (knowledge_store.upload_dir / archive_relpath).resolve()
        if root not in preview_path.parents:
            return
        preview_path.unlink(missing_ok=True)

    @staticmethod
    def _message_for(code: str | None) -> str:
        return {
            "session_expired": "学习通会话已过期，请重新扫码。",
            "verification_required": "学习通要求额外验证，请重新扫码。",
            "file_too_large": "文件超过 100 MB，无法导入。",
            "invalid_file_content": "文件内容校验失败。",
            "upstream_unavailable": "学习通暂时不可用，请稍后重试。",
            "upstream_changed": "学习通页面结构发生变化，请稍后重试。",
            "upstream_response_too_large": "学习通返回内容过大，已停止读取。",
            "upstream_timeout": "读取学习通目录超时，请稍后重试。",
            "catalog_budget_exceeded": "课程目录过大，已停止继续抓取。",
        }.get(code or "", "资料导入失败，请稍后重试。")

    def _cleanup_job_temp(self, workspace_id: str, job_id: str) -> None:
        path = (
            self.service.knowledge_store.upload_dir
            / "tmp"
            / workspace_id
            / job_id
        )
        shutil.rmtree(path, ignore_errors=True)
