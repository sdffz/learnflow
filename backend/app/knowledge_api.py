from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, Response

from .auth import AuthContext, AuthManager
from .ingestion import (
    MAX_UPLOAD_BYTES,
    TextExtraction,
    extract_text,
    inspect_uploaded_file,
    validate_upload,
)
from .knowledge_domain import (
    AssetDetail,
    Course,
    CourseCreate,
    CourseUpdate,
    KnowledgeOverview,
    KnowledgeSearchResponse,
    NoteCreate,
)
from .knowledge_store import KnowledgeStore

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def _split_tags(value: str) -> list[str]:
    return [
        item.strip() for item in value.replace("，", ",").split(",") if item.strip()
    ]


async def _save_upload(upload: UploadFile, destination: Path) -> int:
    size = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as stream:
        while chunk := await upload.read(64 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                stream.close()
                destination.unlink(missing_ok=True)
                raise ValueError("file_too_large")
            stream.write(chunk)
    return size


def build_knowledge_router(
    store: KnowledgeStore,
    auth_manager: AuthManager,
) -> APIRouter:
    router = APIRouter(
        prefix="/api",
        dependencies=[Depends(auth_manager.require_auth)],
    )

    def asset_detail(asset_id: str, workspace_id: str) -> AssetDetail:
        detail = store.get_asset(asset_id, workspace_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="asset_not_found")
        return detail

    @router.get("/knowledge/overview", response_model=KnowledgeOverview)
    def knowledge_overview(
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> KnowledgeOverview:
        return store.overview(auth.workspace_id)

    @router.get("/knowledge/search", response_model=KnowledgeSearchResponse)
    def search_knowledge(
        q: str = "",
        tag: str = "",
        course_id: str = Query("", alias="courseId"),
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> KnowledgeSearchResponse:
        return store.search(q, tag, course_id, auth.workspace_id)

    @router.get("/courses", response_model=dict)
    def list_courses(
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> dict:
        return {"items": store.list_courses(auth.workspace_id)}

    @router.post("/courses", response_model=Course, status_code=201)
    def create_course(
        request: CourseCreate,
        http_request: Request,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> Course:
        course = store.create_course(request, auth.workspace_id)
        auth_manager.audit(
            workspace_id=auth.workspace_id,
            user_id=auth.user_id,
            action="course.create",
            resource_type="course",
            resource_id=course.id,
            ip_address=http_request.client.host if http_request.client else None,
        )
        return course

    @router.get("/courses/{course_id}", response_model=Course)
    def get_course(
        course_id: str,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> Course:
        course = store.get_course(course_id, auth.workspace_id)
        if course is None:
            raise HTTPException(status_code=404, detail="course_not_found")
        return course

    @router.patch("/courses/{course_id}", response_model=Course)
    def update_course(
        course_id: str,
        request: CourseUpdate,
        http_request: Request,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> Course:
        try:
            course = store.update_course(
                course_id,
                request,
                auth.workspace_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="course_not_found") from exc
        auth_manager.audit(
            workspace_id=auth.workspace_id,
            user_id=auth.user_id,
            action="course.update",
            resource_type="course",
            resource_id=course_id,
            ip_address=http_request.client.host if http_request.client else None,
        )
        return course

    @router.delete("/courses/{course_id}", status_code=204)
    def delete_course(
        course_id: str,
        http_request: Request,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> Response:
        try:
            store.delete_course(course_id, auth.workspace_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="course_not_found") from exc
        auth_manager.audit(
            workspace_id=auth.workspace_id,
            user_id=auth.user_id,
            action="course.delete",
            resource_type="course",
            resource_id=course_id,
            ip_address=http_request.client.host if http_request.client else None,
        )
        return Response(status_code=204)

    @router.get("/courses/{course_id}/assets", response_model=dict)
    def list_assets(
        course_id: str,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> dict:
        try:
            return {
                "items": store.list_assets(
                    course_id,
                    auth.workspace_id,
                )
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="course_not_found") from exc

    @router.post(
        "/courses/{course_id}/assets",
        response_model=AssetDetail,
        status_code=201,
    )
    async def upload_asset(
        course_id: str,
        http_request: Request,
        file: UploadFile = File(...),
        title: str = Form(""),
        tags: str = Form(""),
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> AssetDetail:
        if store.get_course(course_id, auth.workspace_id) is None:
            raise HTTPException(status_code=404, detail="course_not_found")

        original_name = Path(file.filename or "upload").name
        try:
            suffix = validate_upload(original_name, 1)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        temporary = (
            store.upload_dir / auth.workspace_id / course_id / f"{uuid4().hex}{suffix}"
        )
        try:
            size = await _save_upload(file, temporary)
            validate_upload(original_name, size)
        except ValueError as exc:
            temporary.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        try:
            canonical_mime = inspect_uploaded_file(temporary, suffix)
        except ValueError as exc:
            temporary.unlink(missing_ok=True)
            raise HTTPException(
                status_code=422,
                detail="invalid_file_content",
            ) from exc

        try:
            extraction = extract_text(temporary, canonical_mime)
        except Exception as exc:
            extraction = TextExtraction(
                text="",
                status="failed",
                error=f"extract_failed: {exc}",
            )

        try:
            created = store.create_asset(
                course_id=course_id,
                workspace_id=auth.workspace_id,
                kind="image" if suffix in IMAGE_EXTENSIONS else "file",
                title=title.strip() or Path(original_name).stem,
                original_name=original_name,
                mime_type=canonical_mime,
                file_relpath=str(temporary.relative_to(store.upload_dir)),
                extraction=extraction,
                tags=_split_tags(tags),
                size_bytes=size,
            )
            auth_manager.audit(
                workspace_id=auth.workspace_id,
                user_id=auth.user_id,
                action="asset.upload",
                resource_type="asset",
                resource_id=created.id,
                ip_address=(http_request.client.host if http_request.client else None),
            )
            return asset_detail(created.id, auth.workspace_id)
        except ValueError as exc:
            temporary.unlink(missing_ok=True)
            if str(exc) == "workspace_quota_exceeded":
                raise HTTPException(
                    status_code=413,
                    detail="workspace_quota_exceeded",
                ) from exc
            raise
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    @router.post(
        "/courses/{course_id}/notes",
        response_model=AssetDetail,
        status_code=201,
    )
    def create_note(
        course_id: str,
        request: NoteCreate,
        http_request: Request,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> AssetDetail:
        try:
            created = store.create_note(
                course_id,
                request,
                auth.workspace_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="course_not_found") from exc
        except ValueError as exc:
            if str(exc) == "workspace_quota_exceeded":
                raise HTTPException(
                    status_code=413,
                    detail="workspace_quota_exceeded",
                ) from exc
            raise
        auth_manager.audit(
            workspace_id=auth.workspace_id,
            user_id=auth.user_id,
            action="note.create",
            resource_type="asset",
            resource_id=created.id,
            ip_address=http_request.client.host if http_request.client else None,
        )
        return asset_detail(created.id, auth.workspace_id)

    @router.get("/assets/{asset_id}", response_model=AssetDetail)
    def get_asset(
        asset_id: str,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> AssetDetail:
        asset = store.get_asset(asset_id, auth.workspace_id)
        if asset is None:
            raise HTTPException(status_code=404, detail="asset_not_found")
        return asset

    @router.get("/assets/{asset_id}/file")
    def get_asset_file(
        asset_id: str,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> FileResponse:
        record = store.asset_file(asset_id, auth.workspace_id)
        if record is None:
            raise HTTPException(status_code=404, detail="file_not_found")
        path, media_type, original_name = record
        return FileResponse(
            path=path,
            media_type=media_type,
            filename=original_name,
            content_disposition_type=(
                "inline" if media_type.startswith("image/") else "attachment"
            ),
        )

    @router.delete("/assets/{asset_id}", status_code=204)
    def delete_asset(
        asset_id: str,
        http_request: Request,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> Response:
        try:
            store.delete_asset(asset_id, auth.workspace_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="asset_not_found") from exc
        auth_manager.audit(
            workspace_id=auth.workspace_id,
            user_id=auth.user_id,
            action="asset.delete",
            resource_type="asset",
            resource_id=asset_id,
            ip_address=http_request.client.host if http_request.client else None,
        )
        return Response(status_code=204)

    return router
