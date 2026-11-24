import logging
import os
import shutil
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import build_router
from .auth import AuthManager
from .auth_api import build_auth_router
from .chaoxing_adapter import ChaoxingAdapter, decode_connector_key
from .config import load_settings
from .knowledge import KnowledgeBase
from .knowledge_api import build_knowledge_router
from .knowledge_store import KnowledgeStore
from .learning_api import build_learning_router
from .learning_service import LearningService
from .learning_store import LearningStore
from .learning_worker import LearningWorker
from .repository import Repository

logger = logging.getLogger("learnflow.http")


def create_app(
    data_dir: Path | None = None,
    *,
    learning_adapter: object | None = None,
) -> FastAPI:
    backend_root = Path(__file__).resolve().parents[1]
    settings = load_settings()
    runtime_dir = data_dir or (
        Path(settings.runtime_dir)
        if settings.runtime_dir
        else backend_root / "data" / "runtime"
    )
    auth_manager = AuthManager(runtime_dir / "learnflow.sqlite3")
    auth_manager.initialize()
    repository = Repository(runtime_dir / "learnflow.sqlite3")
    repository.initialize()
    knowledge_store = KnowledgeStore(
        runtime_dir / "learnflow.sqlite3",
        runtime_dir / "uploads",
        seed_dir=backend_root / "data" / "knowledge" / "ai_intro",
    )
    knowledge_store.initialize()
    connector_key = decode_connector_key(settings.connector_key)
    connector_enabled = bool(
        settings.chaoxing_enabled and connector_key is not None
    )
    learning_store = LearningStore(
        runtime_dir / "learnflow.sqlite3",
        connector_key,
    )
    learning_store.initialize()
    adapter = learning_adapter or ChaoxingAdapter(enabled=connector_enabled)
    learning_service = LearningService(
        learning_store,
        adapter,
        knowledge_store,
    )
    learning_worker = LearningWorker(
        learning_service,
        runtime_dir=runtime_dir,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        learning_worker.start()
        try:
            yield
        finally:
            learning_worker.stop()

    app = FastAPI(
        title="LearnFlow API",
        version="0.3.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.repository = repository
    app.state.knowledge_store = knowledge_store
    app.state.auth_manager = auth_manager
    app.state.learning_store = learning_store
    app.state.learning_service = learning_service
    app.state.learning_worker = learning_worker
    app.state.learning_connector_enabled = connector_enabled

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id", "").strip()
        if not request_id:
            request_id = uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        auth = getattr(request.state, "auth", None)
        logger.info(
            "request_id=%s method=%s path=%s status=%s duration_ms=%.1f "
            "workspace_id=%s user_id=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            getattr(auth, "workspace_id", "-"),
            getattr(auth, "user_id", "-"),
        )
        return response

    app.include_router(
        build_auth_router(
            auth_manager,
            knowledge_store,
            session_max_age=int(auth_manager.session_ttl.total_seconds()),
        )
    )
    app.include_router(build_knowledge_router(knowledge_store, auth_manager))
    app.include_router(
        build_learning_router(
            learning_service,
            learning_worker,
            auth_manager,
            enabled=connector_enabled,
        )
    )
    app.include_router(
        build_router(
            repository=repository,
            knowledge_base=KnowledgeBase(
                backend_root / "data" / "knowledge" / "ai_intro"
            ),
            data_root=backend_root / "data",
            knowledge_store=knowledge_store,
            auth_manager=auth_manager,
        )
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "model_mode": load_settings().model_mode}

    @app.get("/api/health/live")
    def health_live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/health/ready")
    def health_ready():
        checks = {
            "database": "ok",
            "uploads": "ok",
            "disk": "ok",
        }
        try:
            repository.connection.execute("SELECT 1").fetchone()
            knowledge_store.connection.execute("SELECT 1").fetchone()
            auth_manager.connection.execute("SELECT 1").fetchone()
            learning_store.connection.execute("SELECT 1").fetchone()
        except Exception:
            checks["database"] = "error"
        uploads_dir = runtime_dir / "uploads"
        if not uploads_dir.is_dir() or not os.access(uploads_dir, os.W_OK):
            checks["uploads"] = "error"
        try:
            free_bytes = shutil.disk_usage(runtime_dir).free
            if free_bytes < 100 * 1024 * 1024:
                checks["disk"] = "error"
        except OSError:
            free_bytes = 0
            checks["disk"] = "error"
        status = "ready" if all(value == "ok" for value in checks.values()) else "degraded"
        payload = {
            "status": status,
            "model_mode": load_settings().model_mode,
            "checks": checks,
            "free_disk_bytes": free_bytes,
        }
        return JSONResponse(
            payload,
            status_code=200 if status == "ready" else 503,
        )

    return app


app = create_app()
