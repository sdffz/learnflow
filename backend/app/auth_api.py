from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .auth import (
    SESSION_COOKIE,
    AuthContext,
    AuthIdentity,
    AuthManager,
    LoginRequest,
    RegisterRequest,
    enforce_same_origin,
)
from .knowledge_store import KnowledgeStore


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _set_session_cookie(
    response: Response,
    request: Request,
    token: str,
    max_age: int,
) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )


def build_auth_router(
    manager: AuthManager,
    knowledge_store: KnowledgeStore,
    *,
    session_max_age: int,
) -> APIRouter:
    router = APIRouter(prefix="/api/auth", tags=["auth"])

    @router.post("/register", response_model=AuthIdentity, status_code=201)
    def register(
        payload: RegisterRequest,
        request: Request,
        response: Response,
    ) -> AuthIdentity:
        enforce_same_origin(request)
        ip = _client_ip(request)
        manager.register_limiter.check(ip)
        try:
            result = manager.register(payload, ip_address=ip)
        except ValueError as exc:
            if str(exc) == "email_already_registered":
                raise HTTPException(
                    status_code=409,
                    detail="email_already_registered",
                ) from exc
            raise
        if result.workspace_is_new:
            knowledge_store.ensure_workspace(
                result.identity.workspace.id,
                title="我的知识文件夹",
            )
        _set_session_cookie(
            response,
            request,
            result.token,
            session_max_age,
        )
        return result.identity

    @router.post("/login", response_model=AuthIdentity)
    def login(
        payload: LoginRequest,
        request: Request,
        response: Response,
    ) -> AuthIdentity:
        enforce_same_origin(request)
        ip = _client_ip(request)
        manager.login_limiter.check(f"{ip}:{payload.email.casefold()}")
        try:
            result = manager.login(payload, ip_address=ip)
        except ValueError as exc:
            raise HTTPException(
                status_code=401,
                detail="invalid_credentials",
            ) from exc
        _set_session_cookie(
            response,
            request,
            result.token,
            session_max_age,
        )
        return result.identity

    @router.get("/me", response_model=AuthIdentity)
    def me(context: AuthContext = Depends(manager.require_auth)) -> AuthIdentity:
        return context.public_identity()

    @router.post("/logout", status_code=204)
    def logout(
        request: Request,
        context: AuthContext = Depends(manager.require_auth),
    ) -> Response:
        enforce_same_origin(request)
        manager.logout(request.cookies.get(SESSION_COOKIE), context)
        response = Response(status_code=204)
        response.delete_cookie(
            SESSION_COOKIE,
            path="/",
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
        )
        return response

    return router
