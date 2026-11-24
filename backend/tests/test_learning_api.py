import base64
import io
from datetime import UTC, datetime, timedelta
from zipfile import ZipFile

import httpx
import pytest

from app.learning_domain import (
    FinishLogin,
    PreviewCourse,
    PreviewFile,
    QrLoginTicket,
)
from app.main import create_app

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 32


class FakeLearningAdapter:
    enabled = True

    def __init__(self):
        self.logins: set[str] = set()
        self.connected: set[str] = set()

    def start_login(self):
        login_id = f"login-{len(self.logins) + 1}"
        self.logins.add(login_id)
        return QrLoginTicket(
            id=login_id,
            qr_png=PNG_BYTES,
            expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        )

    def qr_image(self, login_id):
        assert login_id in self.logins
        return PNG_BYTES

    def refresh_login(self, login_id):
        assert login_id in self.logins
        return QrLoginTicket(
            id=login_id,
            qr_png=PNG_BYTES,
            expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            revision=1,
        )

    def login_status(self, login_id):
        if login_id not in self.logins:
            raise ValueError("login_not_found")
        self.connected.add(login_id)
        return FinishLogin(status="connected", remote_nickname="张同学")

    def take_cookies(self, login_id):
        assert login_id in self.connected
        self.logins.remove(login_id)
        self.connected.remove(login_id)
        return {"auth": "session-token"}

    def cancel_login(self, login_id):
        self.logins.discard(login_id)
        self.connected.discard(login_id)

    def catalog(self, cookies):
        assert cookies == {"auth": "session-token"}
        return [
            PreviewCourse(
                id="remote-course",
                title="大学物理",
                documents=[
                    PreviewFile(
                        id="remote-file",
                        name="力学.md",
                        extension=".md",
                        size_bytes=20,
                        supported=True,
                        remote_url="https://mooc1.chaoxing.com/files/mechanics.md",
                    )
                ],
            )
        ]

    def download(self, cookies, source_url, destination, *, expected_size=0):
        content = "# 力学\n\n牛顿运动定律。".encode()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        import hashlib

        return hashlib.sha256(content).hexdigest()


def _enable_connector(monkeypatch):
    monkeypatch.setenv("LEARNFLOW_CHAOXING_ENABLED", "true")
    monkeypatch.setenv(
        "LEARNFLOW_CONNECTOR_KEY",
        base64.urlsafe_b64encode(b"k" * 32).decode(),
    )


async def _client_for(app, base_url="http://test"):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=base_url,
        follow_redirects=True,
    )


async def _register(client, email="owner@example.com"):
    return await client.post(
        "/api/auth/register",
        json={
            "name": "学习用户",
            "email": email,
            "password": "EnterprisePass123!",
        },
    )


@pytest.mark.asyncio
async def test_learning_api_is_private(tmp_path, monkeypatch):
    _enable_connector(monkeypatch)
    app = create_app(tmp_path, learning_adapter=FakeLearningAdapter())
    async with await _client_for(app) as client:
        response = await client.get("/api/learning/chaoxing/status")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_connector_disabled_fails_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("LEARNFLOW_CHAOXING_ENABLED", raising=False)
    app = create_app(tmp_path, learning_adapter=FakeLearningAdapter())
    async with await _client_for(app) as client:
        await _register(client)
        status = await client.get("/api/learning/chaoxing/status")
        login = await client.post("/api/learning/chaoxing/login")

    assert status.status_code == 200
    assert status.json()["enabled"] is False
    assert login.status_code == 503
    assert login.json()["detail"] == "connector_disabled"


@pytest.mark.asyncio
async def test_qr_preview_import_and_job_flow(tmp_path, monkeypatch):
    _enable_connector(monkeypatch)
    fake = FakeLearningAdapter()
    app = create_app(tmp_path, learning_adapter=fake)
    async with await _client_for(app) as client:
        await _register(client)
        started = await client.post("/api/learning/chaoxing/login")
        assert started.status_code == 201
        login_id = started.json()["id"]

        qr = await client.get(
            f"/api/learning/chaoxing/login/{login_id}/qr"
        )
        finished = await client.get(
            f"/api/learning/chaoxing/login/{login_id}"
        )
        status = await client.get("/api/learning/chaoxing/status")
        preview = await client.post("/api/learning/chaoxing/previews")

        assert qr.status_code == 200
        assert qr.content.startswith(b"\x89PNG")
        assert finished.status_code == 200
        assert finished.json()["status"] == "connected"
        assert status.json()["connection"]["remoteNickname"] == "张同学"
        assert preview.status_code == 201
        preview_payload = preview.json()
        assert preview_payload["totalDocuments"] == 1
        assert "remoteUrl" not in str(preview_payload)

        created = await client.post(
            "/api/learning/imports",
            json={
                "previewId": preview_payload["id"],
                "mappings": [
                    {
                        "previewCourseId": "remote-course",
                        "mode": "new",
                        "folderTitle": "大学物理（学习通）",
                    }
                ],
            },
        )
        assert created.status_code == 201
        job_id = created.json()["id"]
        detail = await client.get(f"/api/learning/imports/{job_id}")
        assert detail.status_code == 200
        assert detail.json()["job"]["totalItems"] == 1
        assert len(detail.json()["items"]) == 1

        cancelled = await client.post(
            f"/api/learning/imports/{job_id}/cancel"
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_login_and_job_are_hidden_from_other_users(tmp_path, monkeypatch):
    _enable_connector(monkeypatch)
    app = create_app(tmp_path, learning_adapter=FakeLearningAdapter())
    async with await _client_for(app) as first, await _client_for(app) as second:
        await _register(first, "first@example.com")
        await _register(second, "second@example.com")

        login = await first.post("/api/learning/chaoxing/login")
        login_id = login.json()["id"]
        foreign_qr = await second.get(
            f"/api/learning/chaoxing/login/{login_id}/qr"
        )
        foreign_status = await second.get(
            f"/api/learning/chaoxing/login/{login_id}"
        )

    assert foreign_qr.status_code == 404
    assert foreign_status.status_code == 404


@pytest.mark.asyncio
async def test_zip_preview_accepts_safe_archive_and_rejects_traversal(
    tmp_path,
    monkeypatch,
):
    _enable_connector(monkeypatch)
    app = create_app(tmp_path, learning_adapter=FakeLearningAdapter())
    safe_buffer = io.BytesIO()
    with ZipFile(safe_buffer, "w") as archive:
        archive.writestr("数据结构/链表.md", "# 链表\n\n节点通过指针连接。")
    unsafe_buffer = io.BytesIO()
    with ZipFile(unsafe_buffer, "w") as archive:
        archive.writestr("../escape.md", "unsafe")

    async with await _client_for(app) as client:
        await _register(client)
        safe = await client.post(
            "/api/learning/imports/zip/previews",
            files={
                "file": (
                    "资料.zip",
                    safe_buffer.getvalue(),
                    "application/zip",
                )
            },
        )
        unsafe = await client.post(
            "/api/learning/imports/zip/previews",
            files={
                "file": (
                    "unsafe.zip",
                    unsafe_buffer.getvalue(),
                    "application/zip",
                )
            },
        )

    assert safe.status_code == 201
    assert safe.json()["totalDocuments"] == 1
    assert safe.json()["courses"][0]["title"] == "数据结构"
    assert unsafe.status_code == 422
    assert unsafe.json()["detail"] == "invalid_zip_member"


@pytest.mark.asyncio
async def test_zip_import_remains_available_when_connector_is_disabled(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("LEARNFLOW_CHAOXING_ENABLED", raising=False)
    app = create_app(tmp_path, learning_adapter=FakeLearningAdapter())
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("离散数学/集合.md", "# 集合\n\n确定对象的整体。")

    async with await _client_for(app) as client:
        await _register(client)
        preview = await client.post(
            "/api/learning/imports/zip/previews",
            files={
                "file": (
                    "资料.zip",
                    buffer.getvalue(),
                    "application/zip",
                )
            },
        )
        assert preview.status_code == 201
        created = await client.post(
            "/api/learning/imports",
            json={
                "previewId": preview.json()["id"],
                "mappings": [
                    {
                        "previewCourseId": preview.json()["courses"][0]["id"],
                        "mode": "new",
                    }
                ],
            },
        )
        assert created.status_code == 201
        job_id = created.json()["id"]
        identity = (await client.get("/api/auth/me")).json()
        workspace_id = identity["workspace"]["id"]
        user_id = identity["user"]["id"]
        items = app.state.learning_store.list_job_items(
            workspace_id,
            user_id,
            job_id,
        )
        app.state.learning_store.update_job_item(
            workspace_id=workspace_id,
            user_id=user_id,
            job_id=job_id,
            item_id=items[0].id,
            status="failed",
            error_code="upstream_unavailable",
        )
        app.state.learning_store.update_job(
            workspace_id=workspace_id,
            user_id=user_id,
            job_id=job_id,
            status="partial_failed",
            failed_items=1,
        )
        retried = await client.post(f"/api/learning/imports/{job_id}/retry")
        assert retried.status_code == 200
        assert retried.json()["status"] == "queued"
        app.state.learning_worker.run_once(job_id=job_id)
        detail = await client.get(f"/api/learning/imports/{job_id}")

    assert detail.status_code == 200
    assert detail.json()["job"]["status"] == "completed"
