from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest

from app.knowledge_domain import CourseCreate
from app.knowledge_store import KnowledgeStore
from app.learning_domain import FolderMapping, PreviewCourse, PreviewFile
from app.learning_service import LearningService
from app.learning_store import LearningStore


class FakeAdapter:
    def __init__(self, courses):
        self.courses = courses
        self.catalog_calls = 0

    def catalog(self, cookies):
        self.catalog_calls += 1
        assert cookies == {"auth": "session-token"}
        return self.courses


def _services(tmp_path):
    db = tmp_path / "learnflow.sqlite3"
    knowledge = KnowledgeStore(db, tmp_path / "uploads")
    knowledge.initialize()
    learning = LearningStore(db, connector_key=b"k" * 32)
    learning.initialize()
    learning.save_connection(
        workspace_id="w1",
        user_id="u1",
        remote_nickname="张同学",
        cookies={"auth": "session-token"},
        expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    )
    adapter = FakeAdapter(
        [
            PreviewCourse(
                id="remote-course-1",
                title="高等数学",
                teacher="张老师",
                documents=[
                    PreviewFile(
                        id="file-1",
                        name="第一章.pdf",
                        extension=".pdf",
                        size_bytes=120,
                        supported=True,
                        remote_url="https://mooc1.chaoxing.com/files/1.pdf",
                    ),
                    PreviewFile(
                        id="file-2",
                        name="资料包.zip",
                        extension=".zip",
                        size_bytes=80,
                        supported=False,
                        excluded_reason="unsupported_file_type",
                    ),
                ],
                video_links=["https://mooc1.chaoxing.com/video/1.mp4"],
            )
        ]
    )
    return (
        knowledge,
        learning,
        adapter,
        LearningService(learning, adapter, knowledge),
    )


def test_preview_uses_encrypted_connection_and_persists_metadata(tmp_path):
    _knowledge, _learning, adapter, service = _services(tmp_path)

    preview = service.create_preview("w1", "u1")

    assert adapter.catalog_calls == 1
    assert preview.total_documents == 2
    assert preview.total_bytes == 120
    assert preview.total_video_links == 1
    assert preview.courses[0].documents[1].excluded_reason == "unsupported_file_type"
    assert service.learning_store.get_preview("w2", "u1", preview.id) is None


def test_preview_requires_connected_session(tmp_path):
    _knowledge, _learning, _adapter, service = _services(tmp_path)

    with pytest.raises(ValueError, match="session_expired"):
        service.create_preview("w2", "u2")


def test_import_creates_folder_and_only_supported_items(tmp_path):
    knowledge, _learning, _adapter, service = _services(tmp_path)
    preview = service.create_preview("w1", "u1")

    job = service.create_import(
        "w1",
        "u1",
        preview.id,
        [
            FolderMapping(
                preview_course_id="remote-course-1",
                mode="new",
                folder_title="高数（学习通）",
            )
        ],
    )
    items = service.learning_store.list_job_items("w1", "u1", job.id)
    courses = knowledge.list_courses("w1")

    assert any(course.title == "高数（学习通）" for course in courses)
    assert job.total_items == 2
    assert [item.kind for item in items] == ["file", "video_links"]
    assert items[0].source_url == "https://mooc1.chaoxing.com/files/1.pdf"


def test_mapping_can_merge_into_owned_folder(tmp_path):
    knowledge, _learning, _adapter, service = _services(tmp_path)
    target = knowledge.create_course(CourseCreate(title="我的高数"), "w1")
    preview = service.create_preview("w1", "u1")

    job = service.create_import(
        "w1",
        "u1",
        preview.id,
        [
            FolderMapping(
                preview_course_id="remote-course-1",
                mode="merge",
                target_course_id=target.id,
            )
        ],
    )

    assert job.total_items == 2
    assert all(
        item.target_course_id == target.id
        for item in service.learning_store.list_job_items("w1", "u1", job.id)
    )


def test_mapping_rejects_foreign_course(tmp_path):
    knowledge, _learning, _adapter, service = _services(tmp_path)
    foreign = knowledge.create_course(CourseCreate(title="别人的课程"), "w2")
    preview = service.create_preview("w1", "u1")

    with pytest.raises(ValueError, match="course_not_found"):
        service.create_import(
            "w1",
            "u1",
            preview.id,
            [
                FolderMapping(
                    preview_course_id="remote-course-1",
                    mode="merge",
                    target_course_id=foreign.id,
                )
            ],
        )


def test_failed_job_creation_removes_new_folder(tmp_path):
    knowledge, learning, _adapter, service = _services(tmp_path)
    preview = service.create_preview("w1", "u1")
    original_create_job = learning.create_job

    def fail_create_job(**kwargs):
        raise RuntimeError("job_store_unavailable")

    learning.create_job = fail_create_job
    with pytest.raises(RuntimeError, match="job_store_unavailable"):
        service.create_import(
            "w1",
            "u1",
            preview.id,
            [
                FolderMapping(
                    preview_course_id="remote-course-1",
                    mode="new",
                    folder_title="不应残留的文件夹",
                )
            ],
        )
    learning.create_job = original_create_job

    assert all(
        course.title != "不应残留的文件夹"
        for course in knowledge.list_courses("w1")
    )


def test_cancelled_job_cannot_restart(tmp_path):
    _knowledge, _learning, _adapter, service = _services(tmp_path)
    preview = service.create_preview("w1", "u1")
    job = service.create_import(
        "w1",
        "u1",
        preview.id,
        [FolderMapping(preview_course_id="remote-course-1")],
    )

    cancelled = service.cancel_job("w1", "u1", job.id)

    assert cancelled is not None
    assert cancelled.status == "cancelled"
    with pytest.raises(ValueError, match="invalid_job_state"):
        service.retry_failed("w1", "u1", job.id)


def test_retry_resets_only_failed_items(tmp_path):
    _knowledge, learning, _adapter, service = _services(tmp_path)
    preview = service.create_preview("w1", "u1")
    job = service.create_import(
        "w1",
        "u1",
        preview.id,
        [FolderMapping(preview_course_id="remote-course-1")],
    )
    items = learning.list_job_items("w1", "u1", job.id)
    learning.update_job_item(
        workspace_id="w1",
        user_id="u1",
        job_id=job.id,
        item_id=items[0].id,
        status="completed",
        asset_id="asset-1",
    )
    learning.update_job_item(
        workspace_id="w1",
        user_id="u1",
        job_id=job.id,
        item_id=items[1].id,
        status="failed",
        error_code="download_failed",
    )
    learning.update_job(
        workspace_id="w1",
        user_id="u1",
        job_id=job.id,
        status="partial_failed",
        progress=100,
        completed_items=1,
        failed_items=1,
    )

    retry = service.retry_failed("w1", "u1", job.id)

    assert retry is not None
    assert retry.status == "queued"
    assert retry.failed_items == 0
    retried_items = learning.list_job_items("w1", "u1", job.id)
    assert retried_items[0].status == "completed"
    assert retried_items[1].status == "queued"


def test_disconnect_revokes_only_current_user(tmp_path):
    _knowledge, learning, _adapter, service = _services(tmp_path)
    learning.save_connection(
        workspace_id="w1",
        user_id="u2",
        remote_nickname="另一位",
        cookies={"auth": "other"},
        expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    )

    service.disconnect("w1", "u1")

    assert learning.load_connection("w1", "u1") is None
    assert learning.load_connection("w1", "u2") is not None


class LoginAdapter:
    enabled = True

    def __init__(self):
        self.cancelled = []
        self.counter = 0

    def start_login(self):
        from app.learning_domain import QrLoginTicket

        self.counter += 1
        return QrLoginTicket(
            id=f"login-{self.counter}",
            qr_png=b"\x89PNG",
            expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        )

    def cancel_login(self, login_id):
        self.cancelled.append(login_id)

    def qr_image(self, login_id):
        return b"\x89PNG"


def test_one_active_qr_login_per_user(tmp_path):
    knowledge = KnowledgeStore(tmp_path / "db.sqlite3", tmp_path / "uploads")
    knowledge.initialize()
    learning = LearningStore(tmp_path / "db.sqlite3", b"k" * 32)
    learning.initialize()
    adapter = LoginAdapter()
    service = LearningService(learning, adapter, knowledge)

    first = service.begin_login("w1", "u1")
    second = service.begin_login("w1", "u1")

    assert first.id != second.id
    assert adapter.cancelled == [first.id]
    with pytest.raises(ValueError, match="login_not_found"):
        service.qr_image(first.id, "w1", "u1")


def test_concurrent_login_start_is_atomic_per_user(tmp_path):
    knowledge = KnowledgeStore(tmp_path / "db2.sqlite3", tmp_path / "uploads2")
    knowledge.initialize()
    learning = LearningStore(tmp_path / "db2.sqlite3", b"k" * 32)
    learning.initialize()

    class BlockingLoginAdapter(LoginAdapter):
        def __init__(self):
            super().__init__()
            self.entered = Event()
            self.release = Event()

        def start_login(self):
            self.entered.set()
            self.release.wait(timeout=2)
            return super().start_login()

    adapter = BlockingLoginAdapter()
    service = LearningService(learning, adapter, knowledge)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(service.begin_login, "w1", "u1")
        assert adapter.entered.wait(timeout=1)
        with pytest.raises(ValueError, match="login_in_progress"):
            service.begin_login("w1", "u1")
        adapter.release.set()
        ticket = first.result(timeout=2)

    assert service.qr_image(ticket.id, "w1", "u1").startswith(b"\x89PNG")
