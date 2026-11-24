import httpx
import pytest

from app.main import create_app


@pytest.mark.asyncio
async def test_health_reports_mock_mode(monkeypatch):
    monkeypatch.delenv("LEARNFLOW_MODEL_API_KEY", raising=False)

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model_mode": "mock"}


def test_create_app_uses_configured_runtime_directory(monkeypatch, tmp_path):
    runtime_dir = tmp_path / "persistent-data"
    monkeypatch.setenv("LEARNFLOW_DATA_DIR", str(runtime_dir))

    app = create_app()

    assert app.state.repository.db_path == runtime_dir / "learnflow.sqlite3"
    assert runtime_dir.exists()


@pytest.mark.asyncio
async def test_liveness_readiness_and_request_id(tmp_path):
    transport = httpx.ASGITransport(app=create_app(data_dir=tmp_path))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        live = await client.get("/api/health/live")
        ready = await client.get("/api/health/ready")

    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    assert ready.status_code == 200
    assert ready.json()["checks"]["database"] == "ok"
    assert ready.json()["checks"]["uploads"] == "ok"
    assert ready.headers["x-request-id"]
