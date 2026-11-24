import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zipfile import ZipFile

from app.chaoxing_adapter import ChaoxingAdapterError
from app.knowledge_store import KnowledgeStore
from app.learning_domain import FolderMapping, PreviewCourse, PreviewFile
from app.learning_service import LearningService
from app.learning_store import LearningStore
from app.learning_worker import LearningWorker
from app.zip_import import inspect_zip


class WorkerAdapter:
    enabled = True

    def __init__(self):
        self.fail_urls: set[str] = set()
        self.on_download = None
        self.courses = [
            PreviewCourse(
                id="remote-course",
                title="计算机网络",
                documents=[
                    PreviewFile(
                        id="file-1",
                        name="第一章.md",
                        extension=".md",
                        size_bytes=8,
                        supported=True,
                        remote_url="https://mooc1.chaoxing.com/files/1.md",
                    ),
                    PreviewFile(
                        id="file-2",
                        name="第二章.md",
                        extension=".md",
                        size_bytes=8,
                        supported=True,
                        remote_url="https://mooc1.chaoxing.com/files/2.md",
                    ),
                ],
                video_links=["https://mooc1.chaoxing.com/video/1.mp4"],
            )
        ]

    def catalog(self, cookies):
        return self.courses

    def download(self, cookies, source_url, destination: Path, *, expected_size=0):
        if self.on_download:
            self.on_download()
        if source_url in self.fail_urls:
            raise ChaoxingAdapterError("upstream_unavailable")
        content = f"# 学习通资料\n\n来源：{source_url}\n".encode()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return hashlib.sha256(content).hexdigest()


def _worker(tmp_path):
    db = tmp_path / "learnflow.sqlite3"
    knowledge = KnowledgeStore(db, tmp_path / "uploads")
    knowledge.initialize()
    learning = LearningStore(db, b"k" * 32)
    learning.initialize()
    learning.save_connection(
        workspace_id="w1",
        user_id="u1",
        remote_nickname=None,
        cookies={"auth": "session-token"},
        expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    )
    adapter = WorkerAdapter()
    service = LearningService(learning, adapter, knowledge)
    preview = service.create_preview("w1", "u1")
    job = service.create_import(
        "w1",
        "u1",
        preview.id,
        [FolderMapping(preview_course_id="remote-course")],
    )
    return knowledge, learning, adapter, service, job, LearningWorker(
        service,
        runtime_dir=tmp_path,
    )


def test_worker_imports_files_and_video_links(tmp_path):
    knowledge, learning, _adapter, _service, job, worker = _worker(tmp_path)

    worker.run_once(job_id=job.id)

    completed = learning.get_job("w1", "u1", job.id)
    items = learning.list_job_items("w1", "u1", job.id)
    target = next(
        course for course in knowledge.list_courses("w1") if course.title == "计算机网络"
    )
    assets = knowledge.list_assets(target.id, "w1")

    assert completed is not None
    assert completed.status == "completed"
    assert completed.progress == 100
    assert all(item.status == "completed" for item in items)
    assert len(assets) == 3
    assert any(asset.kind == "note" and "视频资料" in asset.title for asset in assets)
    assert knowledge.search(
        "mooc1.chaoxing.com/video/1.mp4",
        course_id=target.id,
        workspace_id="w1",
    ).items
    assert not [
        path for path in (tmp_path / "uploads" / "tmp").rglob("*") if path.is_file()
    ]


def test_worker_partial_failure_retries_only_failed_items(tmp_path):
    _knowledge, learning, adapter, service, job, worker = _worker(tmp_path)
    adapter.fail_urls.add("https://mooc1.chaoxing.com/files/2.md")

    worker.run_once(job_id=job.id)

    failed = learning.get_job("w1", "u1", job.id)
    assert failed is not None
    assert failed.status == "partial_failed"
    assert failed.completed_items == 2
    assert failed.failed_items == 1

    adapter.fail_urls.clear()
    service.retry_failed("w1", "u1", job.id)
    worker.run_once(job_id=job.id)

    retried = learning.get_job("w1", "u1", job.id)
    items = learning.list_job_items("w1", "u1", job.id)
    assert retried is not None
    assert retried.status == "completed"
    assert all(item.status == "completed" for item in items)
    assert [item.attempts for item in items] == [1, 2, 1]


def test_worker_marks_job_session_expired(tmp_path):
    _knowledge, learning, _adapter, _service, job, worker = _worker(tmp_path)
    learning.revoke_connection("w1", "u1")

    worker.run_once(job_id=job.id)

    result = learning.get_job("w1", "u1", job.id)
    assert result is not None
    assert result.status == "session_expired"
    assert result.error_code == "session_expired"


def test_disconnect_prevents_remaining_online_downloads(tmp_path):
    _knowledge, learning, adapter, service, job, worker = _worker(tmp_path)
    adapter.on_download = lambda: service.disconnect("w1", "u1")

    worker.run_once(job_id=job.id)

    result = learning.get_job("w1", "u1", job.id)
    items = learning.list_job_items("w1", "u1", job.id)
    assert result is not None
    assert result.status == "session_expired"
    assert items[0].status == "completed"
    assert items[1].status == "queued"
    assert items[2].status == "queued"


def test_worker_exposes_downloading_and_parsing_states(tmp_path, monkeypatch):
    knowledge, learning, adapter, _service, job, worker = _worker(tmp_path)
    observed: list[str] = []

    def record_download():
        row = learning.connection.execute(
            "SELECT status FROM learning_import_jobs WHERE id = ?",
            (job.id,),
        ).fetchone()
        observed.append(row["status"])

    original_upsert = knowledge.upsert_external_asset

    def record_upsert(*args, **kwargs):
        row = learning.connection.execute(
            "SELECT status FROM learning_import_jobs WHERE id = ?",
            (job.id,),
        ).fetchone()
        observed.append(row["status"])
        return original_upsert(*args, **kwargs)

    adapter.on_download = record_download
    monkeypatch.setattr(knowledge, "upsert_external_asset", record_upsert)

    worker.run_once(job_id=job.id)

    assert observed[0] == "downloading"
    assert "parsing" in observed


def test_interrupted_jobs_are_recovered_as_queued(tmp_path):
    _knowledge, learning, _adapter, _service, job, _worker_instance = _worker(tmp_path)
    learning.update_job(
        workspace_id="w1",
        user_id="u1",
        job_id=job.id,
        status="downloading",
        started_at=datetime.now(UTC).isoformat(),
    )

    recovered = learning.recover_interrupted_jobs()
    result = learning.get_job("w1", "u1", job.id)

    assert recovered == 1
    assert result is not None
    assert result.status == "queued"
    assert result.started_at is None


def test_worker_imports_zip_members_and_cleans_archive(tmp_path):
    db = tmp_path / "learnflow.sqlite3"
    knowledge = KnowledgeStore(db, tmp_path / "uploads")
    knowledge.initialize()
    learning = LearningStore(db, b"k" * 32)
    learning.initialize()
    adapter = WorkerAdapter()
    service = LearningService(learning, adapter, knowledge)
    archive_relpath = Path("tmp/zip/w1/zip-preview.zip")
    archive_path = knowledge.upload_dir / archive_relpath
    archive_path.parent.mkdir(parents=True)
    with ZipFile(archive_path, "w") as zf:
        zf.writestr("离散数学/集合.md", "# 集合\n\n集合是确定对象的整体。")
    preview = service.create_zip_preview(
        "w1",
        "u1",
        str(archive_relpath),
        inspect_zip(archive_path),
        preview_id="zip-preview",
    )
    job = service.create_import(
        "w1",
        "u1",
        preview.id,
        [FolderMapping(preview_course_id=preview.courses[0].id)],
    )
    worker = LearningWorker(service, runtime_dir=tmp_path)

    worker.run_once(job_id=job.id)

    result = learning.get_job("w1", "u1", job.id)
    assert result is not None
    assert result.status == "completed"
    assert knowledge.search("确定对象的整体", workspace_id="w1").items
    assert not archive_path.exists()


def test_worker_cleans_expired_and_orphaned_zip_archives(tmp_path):
    knowledge = KnowledgeStore(tmp_path / "db.sqlite3", tmp_path / "uploads")
    knowledge.initialize()
    learning = LearningStore(tmp_path / "db.sqlite3", b"k" * 32)
    learning.initialize()
    service = LearningService(learning, WorkerAdapter(), knowledge)
    worker = LearningWorker(service, runtime_dir=tmp_path)
    archive_relpath = Path("tmp/zip/w1/expired.zip")
    expired_path = knowledge.upload_dir / archive_relpath
    expired_path.parent.mkdir(parents=True)
    expired_path.write_bytes(b"PK")
    from app.learning_domain import PreviewCourse, PreviewFile

    service.create_zip_preview(
        "w1",
        "u1",
        str(archive_relpath),
        [
            PreviewCourse(
                id="course",
                title="过期课程",
                documents=[
                    PreviewFile(
                        id="file",
                        name="a.md",
                        extension=".md",
                        archive_member="过期课程/a.md",
                    )
                ],
            )
        ],
        preview_id="expired",
    )
    with learning.connection:
        learning.connection.execute(
            "UPDATE learning_previews SET expires_at = ? WHERE id = 'expired'",
            ((datetime.now(UTC) - timedelta(minutes=1)).isoformat(),),
        )
    orphan = knowledge.upload_dir / "tmp" / "zip" / "w1" / "orphan.zip"
    orphan.write_bytes(b"PK")
    old_time = (datetime.now(UTC) - timedelta(hours=1)).timestamp()
    os.utime(orphan, (old_time, old_time))

    removed = worker.cleanup_expired_archives()

    assert removed == 2
    assert not expired_path.exists()
    assert not orphan.exists()
