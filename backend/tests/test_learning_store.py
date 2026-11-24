from datetime import UTC, datetime, timedelta

import pytest

from app.learning_domain import ImportJobItem, PreviewCourse, PreviewFile
from app.learning_store import LearningStore


def _store(tmp_path, key: bytes | None = b"k" * 32) -> LearningStore:
    store = LearningStore(tmp_path / "learnflow.sqlite3", connector_key=key)
    store.initialize()
    return store


def _future(hours: int = 1) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


def test_connection_session_is_encrypted_and_scoped(tmp_path):
    store = _store(tmp_path)
    store.save_connection(
        workspace_id="w1",
        user_id="u1",
        remote_nickname="同学",
        cookies={"auth": "secret-cookie"},
        expires_at=_future(),
        account_fingerprint="fingerprint",
    )

    loaded = store.load_connection("w1", "u1")

    assert loaded is not None
    assert loaded.cookies == {"auth": "secret-cookie"}
    assert loaded.remote_nickname == "同学"
    assert store.load_connection("w2", "u1") is None
    assert (
        "secret-cookie"
        not in (tmp_path / "learnflow.sqlite3")
        .read_bytes()
        .decode("utf-8", errors="ignore")
    )

    store.revoke_connection("w1", "u1")
    assert store.load_connection("w1", "u1") is None


def test_connection_requires_key_and_fails_closed_without_it(tmp_path):
    store = _store(tmp_path, key=None)
    store.save_connection(
        workspace_id="w1",
        user_id="u1",
        remote_nickname=None,
        cookies={"auth": "secret"},
        expires_at=_future(),
    )

    loaded = store.load_connection("w1", "u1")

    assert loaded is not None
    assert loaded.status == "error"
    assert loaded.cookies is None


def test_tampered_ciphertext_fails_closed(tmp_path):
    store = _store(tmp_path)
    store.save_connection(
        workspace_id="w1",
        user_id="u1",
        remote_nickname=None,
        cookies={"auth": "secret"},
        expires_at=_future(),
    )
    with store.connection:
        store.connection.execute(
            "UPDATE learning_connections SET session_ciphertext = x'00'"
        )

    loaded = store.load_connection("w1", "u1")

    assert loaded is not None
    assert loaded.status == "error"
    assert loaded.cookies is None


def test_expired_connection_is_marked_and_never_returns_cookies(tmp_path):
    store = _store(tmp_path)
    store.save_connection(
        workspace_id="w1",
        user_id="u1",
        remote_nickname=None,
        cookies={"auth": "secret"},
        expires_at=_future(),
    )
    with store.connection:
        store.connection.execute(
            "UPDATE learning_connections SET expires_at = ?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),),
        )

    loaded = store.load_connection("w1", "u1")

    assert loaded is not None
    assert loaded.status == "expired"
    assert loaded.cookies is None


def test_preview_round_trip_is_scoped_to_workspace_and_user(tmp_path):
    store = _store(tmp_path)
    course = PreviewCourse(
        id="course-1",
        title="高等数学",
        teacher="张老师",
        documents=[
            PreviewFile(
                id="file-1",
                name="第一章.pdf",
                extension=".pdf",
                size_bytes=120,
                supported=True,
            )
        ],
        video_links=["https://example.chaoxing.com/video/1"],
    )
    preview = store.create_preview(
        workspace_id="w1",
        user_id="u1",
        courses=[course],
        expires_at=_future(),
    )

    loaded = store.get_preview("w1", "u1", preview.id)

    assert loaded is not None
    assert loaded.total_documents == 1
    assert loaded.total_video_links == 1
    assert loaded.courses[0].documents[0].name == "第一章.pdf"
    assert store.get_preview("w2", "u1", preview.id) is None
    assert store.get_preview("w1", "u2", preview.id) is None


def test_import_job_and_items_are_scoped_and_updatable(tmp_path):
    store = _store(tmp_path)
    job = store.create_job(
        workspace_id="w1",
        user_id="u1",
        preview_id="preview-1",
        total_items=2,
        items=[
            ImportJobItem(
                id="item-1",
                job_id="ignored",
                kind="file",
                title="讲义.pdf",
                external_course_id="c1",
                external_file_id="f1",
                target_course_id="course-1",
            ),
            ImportJobItem(
                id="item-2",
                job_id="ignored",
                kind="video_links",
                title="视频资料链接",
                external_course_id="c1",
                external_file_id=None,
                target_course_id="course-1",
            ),
        ],
    )

    assert store.get_job("w2", "u1", job.id) is None
    assert store.get_job("w1", "u2", job.id) is None
    assert [item.id for item in store.list_job_items("w1", "u1", job.id)] == [
        "item-1",
        "item-2",
    ]

    store.update_job_item(
        workspace_id="w1",
        user_id="u1",
        job_id=job.id,
        item_id="item-1",
        status="completed",
        asset_id="asset-1",
        checksum="abc",
    )
    updated = store.update_job(
        workspace_id="w1",
        user_id="u1",
        job_id=job.id,
        status="completed",
        progress=100,
        completed_items=2,
    )

    assert updated is not None
    assert updated.status == "completed"
    assert updated.progress == 100
    items = store.list_job_items("w1", "u1", job.id)
    assert items[0].status == "completed"
    assert items[0].asset_id == "asset-1"


def test_invalid_connection_expiry_is_rejected(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(ValueError, match="invalid_expiry"):
        store.save_connection(
            workspace_id="w1",
            user_id="u1",
            remote_nickname=None,
            cookies={"auth": "secret"},
            expires_at="not-a-date",
        )
