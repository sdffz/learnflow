from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile

from .auth import AuthContext, AuthManager, LoginRateLimiter
from .chaoxing_adapter import ChaoxingAdapterError
from .learning_domain import (
    CreateImportRequest,
    FinishLogin,
    ImportJob,
    ImportPreview,
    JobDetail,
    LearningLogin,
    LearningStatus,
)
from .learning_service import LearningService
from .learning_worker import LearningWorker
from .zip_import import inspect_zip

MAX_ZIP_UPLOAD_BYTES = 250 * 1024 * 1024

ERROR_STATUS = {
    "connector_disabled": 503,
    "login_not_found": 404,
    "login_expired": 410,
    "login_cancelled": 409,
    "login_not_connected": 409,
    "login_in_progress": 409,
    "session_expired": 409,
    "verification_required": 409,
    "source_permission_denied": 403,
    "preview_not_found": 404,
    "preview_course_not_found": 422,
    "course_not_found": 404,
    "nothing_selected": 422,
    "nothing_to_import": 422,
    "target_course_required": 422,
    "duplicate_mapping": 422,
    "invalid_job_state": 409,
    "file_too_large": 413,
    "invalid_file_content": 422,
    "invalid_zip_file": 422,
    "invalid_zip_member": 422,
    "nested_archive": 422,
    "unsupported_zip_type": 422,
    "too_many_zip_members": 422,
    "zip_too_large": 413,
    "empty_zip": 422,
    "upstream_unavailable": 502,
    "upstream_changed": 502,
    "upstream_response_too_large": 502,
    "upstream_timeout": 504,
    "catalog_budget_exceeded": 502,
}


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _raise_learning_error(exc: Exception) -> None:
    code = exc.code if isinstance(exc, ChaoxingAdapterError) else str(exc)
    raise HTTPException(
        status_code=ERROR_STATUS.get(code, 422),
        detail=code,
    ) from exc


async def _save_zip(upload: UploadFile, destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        with destination.open("wb") as stream:
            while chunk := await upload.read(64 * 1024):
                size += len(chunk)
                if size > MAX_ZIP_UPLOAD_BYTES:
                    raise ValueError("zip_too_large")
                stream.write(chunk)
        if size == 0:
            raise ValueError("empty_zip")
        return size
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def build_learning_router(
    service: LearningService,
    worker: LearningWorker,
    auth_manager: AuthManager,
    *,
    enabled: bool,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/learning",
        tags=["learning"],
        dependencies=[Depends(auth_manager.require_auth)],
    )
    start_limiter = LoginRateLimiter(limit=5, window_seconds=3600)
    preview_limiter = LoginRateLimiter(limit=5, window_seconds=3600)

    def require_enabled() -> None:
        if not enabled:
            raise HTTPException(status_code=503, detail="connector_disabled")

    def audit(
        auth: AuthContext,
        request: Request,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        auth_manager.audit(
            workspace_id=auth.workspace_id,
            user_id=auth.user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata=metadata,
            ip_address=_client_ip(request),
        )

    @router.get("/chaoxing/status", response_model=LearningStatus)
    def status(
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> LearningStatus:
        result = service.status(auth.workspace_id, auth.user_id)
        result.enabled = enabled
        if not enabled:
            result.connection = None
        return result

    @router.post(
        "/chaoxing/login",
        response_model=LearningLogin,
        status_code=201,
    )
    def start_login(
        request: Request,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> LearningLogin:
        require_enabled()
        start_limiter.check(auth.user_id)
        try:
            ticket = service.begin_login(auth.workspace_id, auth.user_id)
        except Exception as exc:
            _raise_learning_error(exc)
        audit(
            auth,
            request,
            "learning.login.start",
            "learning_login",
            ticket.id,
        )
        return LearningLogin(
            id=ticket.id,
            status="pending",
            expires_at=ticket.expires_at,
            revision=ticket.revision,
        )

    @router.get(
        "/chaoxing/login/{login_id}",
        response_model=FinishLogin,
    )
    def poll_login(
        login_id: str,
        request: Request,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> FinishLogin:
        require_enabled()
        try:
            result = service.finish_login(
                login_id,
                auth.workspace_id,
                auth.user_id,
            )
        except Exception as exc:
            _raise_learning_error(exc)
        if result.status == "connected":
            audit(
                auth,
                request,
                "learning.login.connected",
                "learning_connection",
                "chaoxing",
                {"remoteNickname": result.remote_nickname},
            )
        return result

    @router.get("/chaoxing/login/{login_id}/qr")
    def qr_image(
        login_id: str,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> Response:
        require_enabled()
        try:
            image = service.qr_image(
                login_id,
                auth.workspace_id,
                auth.user_id,
            )
        except Exception as exc:
            _raise_learning_error(exc)
        return Response(
            content=image,
            media_type="image/png",
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    @router.post(
        "/chaoxing/login/{login_id}/refresh",
        response_model=LearningLogin,
    )
    def refresh_login(
        login_id: str,
        request: Request,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> LearningLogin:
        require_enabled()
        try:
            ticket = service.refresh_login(
                login_id,
                auth.workspace_id,
                auth.user_id,
            )
        except Exception as exc:
            _raise_learning_error(exc)
        audit(
            auth,
            request,
            "learning.login.refresh",
            "learning_login",
            login_id,
        )
        return LearningLogin(
            id=ticket.id,
            status="pending",
            expires_at=ticket.expires_at,
            revision=ticket.revision,
        )

    @router.delete("/chaoxing/login/{login_id}", status_code=204)
    def cancel_login(
        login_id: str,
        request: Request,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> Response:
        require_enabled()
        try:
            service.cancel_login(
                login_id,
                auth.workspace_id,
                auth.user_id,
            )
        except Exception as exc:
            _raise_learning_error(exc)
        audit(
            auth,
            request,
            "learning.login.cancel",
            "learning_login",
            login_id,
        )
        return Response(status_code=204)

    @router.delete("/chaoxing/connection", status_code=204)
    def disconnect(
        request: Request,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> Response:
        require_enabled()
        service.disconnect(auth.workspace_id, auth.user_id)
        audit(
            auth,
            request,
            "learning.connection.disconnect",
            "learning_connection",
            "chaoxing",
        )
        return Response(status_code=204)

    @router.post(
        "/chaoxing/previews",
        response_model=ImportPreview,
        status_code=201,
    )
    def create_preview(
        request: Request,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> ImportPreview:
        require_enabled()
        preview_limiter.check(auth.user_id)
        try:
            preview = service.create_preview(auth.workspace_id, auth.user_id)
        except Exception as exc:
            _raise_learning_error(exc)
        audit(
            auth,
            request,
            "learning.preview.create",
            "learning_preview",
            preview.id,
            {
                "courseCount": len(preview.courses),
                "documentCount": preview.total_documents,
            },
        )
        return preview

    @router.post(
        "/imports/zip/previews",
        response_model=ImportPreview,
        status_code=201,
    )
    async def create_zip_preview(
        request: Request,
        file: UploadFile = File(...),
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> ImportPreview:
        preview_limiter.check(auth.user_id)
        original_name = Path(file.filename or "导入资料.zip").name
        if Path(original_name).suffix.casefold() != ".zip":
            raise HTTPException(status_code=422, detail="unsupported_zip_type")
        preview_id = uuid4().hex
        archive_relpath = (
            Path("tmp") / "zip" / auth.workspace_id / f"{preview_id}.zip"
        )
        destination = service.knowledge_store.upload_dir / archive_relpath
        try:
            await _save_zip(file, destination)
            courses = inspect_zip(destination)
            if not courses:
                raise ValueError("nothing_to_import")
            preview = service.create_zip_preview(
                auth.workspace_id,
                auth.user_id,
                str(archive_relpath),
                courses,
                preview_id=preview_id,
            )
        except ValueError as exc:
            destination.unlink(missing_ok=True)
            code = str(exc)
            raise HTTPException(
                status_code=ERROR_STATUS.get(code, 422),
                detail=code,
            ) from exc
        audit(
            auth,
            request,
            "learning.zip.preview",
            "learning_preview",
            preview.id,
            {
                "courseCount": len(preview.courses),
                "documentCount": preview.total_documents,
            },
        )
        return preview

    @router.post(
        "/imports",
        response_model=ImportJob,
        status_code=201,
    )
    def create_import(
        payload: CreateImportRequest,
        request: Request,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> ImportJob:
        if not enabled and not service.is_zip_preview(
            auth.workspace_id,
            auth.user_id,
            payload.preview_id,
        ):
            require_enabled()
        try:
            job = service.create_import(
                auth.workspace_id,
                auth.user_id,
                payload.preview_id,
                payload.mappings,
            )
        except Exception as exc:
            _raise_learning_error(exc)
        worker.wake()
        audit(
            auth,
            request,
            "learning.import.start",
            "learning_import",
            job.id,
            {"totalItems": job.total_items},
        )
        return job

    @router.get("/imports/{job_id}", response_model=JobDetail)
    def get_import(
        job_id: str,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> JobDetail:
        detail = service.get_job_detail(
            auth.workspace_id,
            auth.user_id,
            job_id,
        )
        if detail is None:
            raise HTTPException(status_code=404, detail="import_not_found")
        return detail

    @router.get("/imports/{job_id}/items", response_model=dict)
    def list_import_items(
        job_id: str,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> dict:
        detail = service.get_job_detail(
            auth.workspace_id,
            auth.user_id,
            job_id,
        )
        if detail is None:
            raise HTTPException(status_code=404, detail="import_not_found")
        return {"items": detail.items}

    @router.post("/imports/{job_id}/cancel", response_model=ImportJob)
    def cancel_import(
        job_id: str,
        request: Request,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> ImportJob:
        try:
            job = service.cancel_job(auth.workspace_id, auth.user_id, job_id)
        except Exception as exc:
            _raise_learning_error(exc)
        if job is None:
            raise HTTPException(status_code=404, detail="import_not_found")
        audit(
            auth,
            request,
            "learning.import.cancel",
            "learning_import",
            job_id,
        )
        return job

    @router.post("/imports/{job_id}/retry", response_model=ImportJob)
    def retry_import(
        job_id: str,
        request: Request,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> ImportJob:
        if not enabled and not service.is_zip_job(
            auth.workspace_id,
            auth.user_id,
            job_id,
        ):
            require_enabled()
        try:
            job = service.retry_failed(
                auth.workspace_id,
                auth.user_id,
                job_id,
            )
        except Exception as exc:
            _raise_learning_error(exc)
        if job is None:
            raise HTTPException(status_code=404, detail="import_not_found")
        worker.wake()
        audit(
            auth,
            request,
            "learning.import.retry",
            "learning_import",
            job_id,
        )
        return job

    return router
