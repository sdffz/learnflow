from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import RLock
from uuid import uuid4

from .chaoxing_adapter import ChaoxingAdapter, ChaoxingAdapterError
from .knowledge_domain import CourseCreate
from .knowledge_store import KnowledgeStore
from .learning_domain import (
    FinishLogin,
    FolderMapping,
    ImportJob,
    ImportJobItem,
    ImportPreview,
    JobDetail,
    LearningConnection,
    LearningStatus,
    QrLoginTicket,
)
from .learning_store import LearningStore

PREVIEW_TTL = timedelta(minutes=30)
CONNECTION_TTL = timedelta(hours=24)


class LearningService:
    def __init__(
        self,
        learning_store: LearningStore,
        adapter: ChaoxingAdapter | object,
        knowledge_store: KnowledgeStore,
    ):
        self.learning_store = learning_store
        self.adapter = adapter
        self.knowledge_store = knowledge_store
        self._login_lock = RLock()
        self._login_owners: dict[str, tuple[str, str, str]] = {}
        self._login_starting: set[tuple[str, str]] = set()

    def status(self, workspace_id: str, user_id: str) -> LearningStatus:
        loaded = self.learning_store.load_connection(workspace_id, user_id)
        connection = None
        if loaded is not None:
            connection = LearningConnection.model_validate(
                loaded.model_dump(
                    exclude={"cookies", "account_fingerprint"},
                )
            )
        return LearningStatus(
            enabled=bool(getattr(self.adapter, "enabled", True)),
            connection=connection,
        )

    def begin_login(self, workspace_id: str, user_id: str) -> QrLoginTicket:
        self._sweep_login_owners()
        owner_key = (workspace_id, user_id)
        with self._login_lock:
            if owner_key in self._login_starting:
                raise ValueError("login_in_progress")
            self._login_starting.add(owner_key)
            previous_ids = []
            for login_id, owner in list(self._login_owners.items()):
                if owner[:2] == owner_key:
                    previous_ids.append(login_id)
                    self._login_owners.pop(login_id, None)
        try:
            for login_id in previous_ids:
                self.adapter.cancel_login(login_id)
            ticket = self.adapter.start_login()
        except Exception:
            with self._login_lock:
                self._login_starting.discard(owner_key)
            raise
        with self._login_lock:
            self._login_owners[ticket.id] = (
                workspace_id,
                user_id,
                ticket.expires_at,
            )
            self._login_starting.discard(owner_key)
        return ticket

    def qr_image(
        self,
        login_id: str,
        workspace_id: str,
        user_id: str,
    ) -> bytes:
        self._authorize_login(login_id, workspace_id, user_id)
        return self.adapter.qr_image(login_id)

    def refresh_login(
        self,
        login_id: str,
        workspace_id: str,
        user_id: str,
    ) -> QrLoginTicket:
        self._authorize_login(login_id, workspace_id, user_id)
        return self.adapter.refresh_login(login_id)

    def finish_login(
        self,
        login_id: str,
        workspace_id: str,
        user_id: str,
    ) -> FinishLogin:
        self._authorize_login(login_id, workspace_id, user_id)
        result = self.adapter.login_status(login_id)
        if result.status != "connected":
            if result.status in {"cancelled", "expired", "verification_required"}:
                self.adapter.cancel_login(login_id)
                self._forget_login(login_id)
            return result
        cookies = self.adapter.take_cookies(login_id)
        self.learning_store.save_connection(
            workspace_id=workspace_id,
            user_id=user_id,
            remote_nickname=result.remote_nickname,
            cookies=cookies,
            expires_at=(datetime.now(UTC) + CONNECTION_TTL).isoformat(),
        )
        self._forget_login(login_id)
        return result

    def cancel_login(
        self,
        login_id: str,
        workspace_id: str,
        user_id: str,
    ) -> None:
        self._authorize_login(login_id, workspace_id, user_id)
        self.adapter.cancel_login(login_id)
        self._forget_login(login_id)

    def sweep_expired_logins(self) -> int:
        removed = 0
        sweep = getattr(self.adapter, "sweep_expired", None)
        if sweep:
            removed = sweep()
        self._sweep_login_owners()
        return removed

    def create_preview(
        self,
        workspace_id: str,
        user_id: str,
    ) -> ImportPreview:
        connection = self.learning_store.load_connection(workspace_id, user_id)
        if (
            connection is None
            or connection.status != "connected"
            or not connection.cookies
        ):
            raise ValueError("session_expired")
        try:
            courses = self.adapter.catalog(connection.cookies)
        except ChaoxingAdapterError:
            raise
        except Exception as exc:
            raise ChaoxingAdapterError("upstream_unavailable") from exc
        preview = self.learning_store.create_preview(
            workspace_id=workspace_id,
            user_id=user_id,
            courses=courses,
            expires_at=(datetime.now(UTC) + PREVIEW_TTL).isoformat(),
        )
        self.learning_store.touch_connection(workspace_id, user_id)
        return preview

    def create_zip_preview(
        self,
        workspace_id: str,
        user_id: str,
        archive_relpath: str,
        courses,
        preview_id: str | None = None,
    ) -> ImportPreview:
        return self.learning_store.create_preview(
            workspace_id=workspace_id,
            user_id=user_id,
            courses=courses,
            expires_at=(datetime.now(UTC) + PREVIEW_TTL).isoformat(),
            archive_relpath=archive_relpath,
            preview_id=preview_id,
        )

    def create_import(
        self,
        workspace_id: str,
        user_id: str,
        preview_id: str,
        mappings: list[FolderMapping],
    ) -> ImportJob:
        preview = self.learning_store.get_preview(
            workspace_id,
            user_id,
            preview_id,
        )
        if preview is None:
            raise ValueError("preview_not_found")
        if not mappings:
            raise ValueError("nothing_selected")
        courses = {course.id: course for course in preview.courses}
        mapping_by_course: dict[str, FolderMapping] = {}
        for mapping in mappings:
            if mapping.preview_course_id not in courses:
                raise ValueError("preview_course_not_found")
            if mapping.preview_course_id in mapping_by_course:
                raise ValueError("duplicate_mapping")
            mapping_by_course[mapping.preview_course_id] = mapping

        selected_counts: dict[str, int] = {}
        for course_id, mapping in mapping_by_course.items():
            if mapping.mode == "skip":
                selected_counts[course_id] = 0
                continue
            course = courses[course_id]
            selected_counts[course_id] = sum(
                1 for file in course.documents if file.supported
            ) + (1 if course.video_links else 0)
        if not any(selected_counts.values()):
            raise ValueError("nothing_to_import")

        merge_targets: dict[str, str] = {}
        for course_id, mapping in mapping_by_course.items():
            if mapping.mode != "merge" or selected_counts[course_id] == 0:
                continue
            if not mapping.target_course_id:
                raise ValueError("target_course_required")
            target = self.knowledge_store.get_course(
                mapping.target_course_id,
                workspace_id,
            )
            if target is None:
                raise ValueError("course_not_found")
            merge_targets[course_id] = target.id

        target_by_course: dict[str, str] = dict(merge_targets)
        created_course_ids: list[str] = []
        try:
            for course_id, mapping in mapping_by_course.items():
                if (
                    mapping.mode == "skip"
                    or mapping.mode == "merge"
                    or selected_counts[course_id] == 0
                ):
                    continue
                course = courses[course_id]
                created = self.knowledge_store.create_course(
                    CourseCreate(
                        title=(mapping.folder_title or course.title).strip()[:80],
                        description="从学习通导入的课程资料，视频仅保留链接。",
                        color="#e25d3f",
                    ),
                    workspace_id,
                )
                created_course_ids.append(created.id)
                target_by_course[course_id] = created.id

            items: list[ImportJobItem] = []
            for course_id, target_course_id in target_by_course.items():
                course = courses[course_id]
                for file in course.documents:
                    if not file.supported:
                        continue
                    items.append(
                        ImportJobItem(
                            id=uuid4().hex,
                            job_id="",
                            kind="zip_file" if file.archive_member else "file",
                            title=file.name,
                            external_course_id=course.id,
                            external_file_id=file.id,
                            target_course_id=target_course_id,
                            source_url=file.remote_url,
                            archive_member=file.archive_member,
                            size_bytes=file.size_bytes,
                        )
                    )
                if course.video_links:
                    items.append(
                        ImportJobItem(
                            id=uuid4().hex,
                            job_id="",
                            kind="video_links",
                            title=f"{course.title} · 视频资料链接",
                            external_course_id=course.id,
                            external_file_id=None,
                            target_course_id=target_course_id,
                            size_bytes=0,
                        )
                    )
            if not items:
                raise ValueError("nothing_to_import")
            return self.learning_store.create_job(
                workspace_id=workspace_id,
                user_id=user_id,
                preview_id=preview.id,
                total_items=len(items),
                items=items,
            )
        except Exception:
            for course_id in created_course_ids:
                try:
                    self.knowledge_store.delete_course(course_id, workspace_id)
                except KeyError:
                    pass
            raise

    def is_zip_preview(
        self,
        workspace_id: str,
        user_id: str,
        preview_id: str,
    ) -> bool:
        return bool(
            self.learning_store.get_preview_archive_relpath(
                workspace_id,
                user_id,
                preview_id,
            )
        )

    def is_zip_job(
        self,
        workspace_id: str,
        user_id: str,
        job_id: str,
    ) -> bool:
        job = self.learning_store.get_job(workspace_id, user_id, job_id)
        return bool(
            job
            and self.learning_store.get_preview_archive_relpath(
                workspace_id,
                user_id,
                job.preview_id,
            )
        )

    def get_job_detail(
        self,
        workspace_id: str,
        user_id: str,
        job_id: str,
    ) -> JobDetail | None:
        job = self.learning_store.get_job(workspace_id, user_id, job_id)
        if job is None:
            return None
        return JobDetail(
            job=job,
            items=self.learning_store.list_job_items(
                workspace_id,
                user_id,
                job_id,
            ),
        )

    def cancel_job(
        self,
        workspace_id: str,
        user_id: str,
        job_id: str,
    ) -> ImportJob | None:
        job = self.learning_store.get_job(workspace_id, user_id, job_id)
        if job is None:
            return None
        if job.status not in {"queued", "reading", "downloading", "parsing"}:
            raise ValueError("invalid_job_state")
        return self.learning_store.update_job(
            workspace_id=workspace_id,
            user_id=user_id,
            job_id=job_id,
            status="cancelled",
            cancel_requested=True,
            finished_at=datetime.now(UTC).isoformat(),
        )

    def retry_failed(
        self,
        workspace_id: str,
        user_id: str,
        job_id: str,
    ) -> ImportJob | None:
        job = self.learning_store.get_job(workspace_id, user_id, job_id)
        if job is None:
            return None
        if job.status not in {"partial_failed", "session_expired"}:
            raise ValueError("invalid_job_state")
        for item in self.learning_store.list_job_items(
            workspace_id,
            user_id,
            job_id,
        ):
            if item.status != "failed":
                continue
            self.learning_store.update_job_item(
                workspace_id=workspace_id,
                user_id=user_id,
                job_id=job_id,
                item_id=item.id,
                status="queued",
                error_code=None,
                error_message=None,
            )
        progress = (
            int(round((job.completed_items + job.skipped_items) / job.total_items * 100))
            if job.total_items
            else 0
        )
        return self.learning_store.update_job(
            workspace_id=workspace_id,
            user_id=user_id,
            job_id=job_id,
            status="queued",
            progress=progress,
            failed_items=0,
            started_at=None,
            finished_at=None,
            error_code=None,
            error_message=None,
        )

    def disconnect(self, workspace_id: str, user_id: str) -> None:
        self.learning_store.expire_online_jobs(workspace_id, user_id)
        self.learning_store.revoke_connection(workspace_id, user_id)

    def _authorize_login(
        self,
        login_id: str,
        workspace_id: str,
        user_id: str,
    ) -> None:
        self._sweep_login_owners()
        with self._login_lock:
            owner = self._login_owners.get(login_id)
        if owner is None or owner[:2] != (workspace_id, user_id):
            raise ValueError("login_not_found")

    def _forget_login(self, login_id: str) -> None:
        with self._login_lock:
            self._login_owners.pop(login_id, None)

    def _sweep_login_owners(self) -> None:
        now = datetime.now(UTC)
        with self._login_lock:
            expired = [
                login_id
                for login_id, (_workspace, _user, expires_at) in (
                    self._login_owners.items()
                )
                if datetime.fromisoformat(expires_at) <= now
            ]
        for login_id in expired:
            self.adapter.cancel_login(login_id)
            self._forget_login(login_id)
