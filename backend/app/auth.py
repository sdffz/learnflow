from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from .domain import utc_now
from .tenancy import DEFAULT_WORKSPACE_ID

SESSION_COOKIE = "learnflow_session"
SESSION_TTL = timedelta(days=7)
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def normalize_email(value: str) -> str:
    return value.strip().casefold()


def enforce_same_origin(request: Request) -> None:
    if request.method.upper() not in MUTATING_METHODS:
        return
    origin = request.headers.get("origin")
    if not origin:
        return
    configured = {
        value.strip().rstrip("/")
        for value in os.getenv("LEARNFLOW_ALLOWED_ORIGINS", "").split(",")
        if value.strip()
    }
    allowed = {
        str(request.base_url).rstrip("/"),
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        *configured,
    }
    if origin.rstrip("/") not in allowed:
        raise HTTPException(
            status_code=403,
            detail="cross_origin_request_rejected",
        )


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("name", "email", mode="before")
    @classmethod
    def trim(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        normalized = normalize_email(value)
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("invalid_email")
        return normalized


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def trim(cls, value: str) -> str:
        return normalize_email(value) if isinstance(value, str) else value


class UserPublic(BaseModel):
    id: str
    name: str
    email: str


class WorkspacePublic(BaseModel):
    id: str
    name: str
    role: Literal["owner", "editor", "viewer"]


class AuthIdentity(BaseModel):
    user: UserPublic
    workspace: WorkspacePublic


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    user_name: str
    email: str
    workspace_id: str
    workspace_name: str
    role: str
    session_hash: str

    def public_identity(self) -> AuthIdentity:
        return AuthIdentity(
            user=UserPublic(
                id=self.user_id,
                name=self.user_name,
                email=self.email,
            ),
            workspace=WorkspacePublic(
                id=self.workspace_id,
                name=self.workspace_name,
                role=self.role,
            ),
        )


@dataclass(frozen=True)
class SessionResult:
    identity: AuthIdentity
    token: str
    expires_at: datetime
    workspace_is_new: bool


class LoginRateLimiter:
    def __init__(self, limit: int = 10, window_seconds: int = 60):
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = datetime.now(UTC).timestamp()
        events = self._events[key]
        boundary = now - self.window_seconds
        while events and events[0] < boundary:
            events.popleft()
        if len(events) >= self.limit:
            raise HTTPException(
                status_code=429,
                detail="rate_limit_exceeded",
                headers={"Retry-After": str(self.window_seconds)},
            )
        events.append(now)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    n = 2**14
    r = 8
    p = 1
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=32,
    )
    return f"scrypt${n}${r}${p}${_encode(salt)}${_encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_value, digest_value = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        expected = _decode(digest_value)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_decode(salt_value),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthManager:
    def __init__(
        self,
        db_path: Path,
        *,
        session_ttl: timedelta = SESSION_TTL,
    ):
        self.db_path = db_path
        self.session_ttl = session_ttl
        self._lock = RLock()
        self._connection: sqlite3.Connection | None = None
        self.login_limiter = LoginRateLimiter()
        self.register_limiter = LoginRateLimiter(limit=20, window_seconds=3600)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._lock, self.connection:
            self.connection.executescript(
                """
                PRAGMA foreign_keys = ON;
                PRAGMA journal_mode = WAL;
                PRAGMA synchronous = NORMAL;
                PRAGMA busy_timeout = 5000;

                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    disabled INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    owner_user_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (owner_user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS workspace_members (
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('owner', 'editor', 'viewer')),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (workspace_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_auth_sessions_user
                    ON auth_sessions(user_id, expires_at);

                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id TEXT,
                    user_id TEXT,
                    action TEXT NOT NULL,
                    resource_type TEXT,
                    resource_id TEXT,
                    metadata_json TEXT NOT NULL,
                    ip_address TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_audit_workspace_time
                    ON audit_events(workspace_id, created_at);
                """
            )
            self.connection.execute(
                """
                INSERT OR IGNORE INTO workspaces
                    (id, name, owner_user_id, created_at, updated_at)
                VALUES (?, ?, NULL, ?, ?)
                """,
                (
                    DEFAULT_WORKSPACE_ID,
                    "默认个人知识空间",
                    utc_now(),
                    utc_now(),
                ),
            )

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("AuthManager is not initialized")
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def register(
        self,
        request: RegisterRequest,
        *,
        ip_address: str | None = None,
    ) -> SessionResult:
        email = normalize_email(request.email)
        now = utc_now()
        user_id = uuid4().hex
        with self._lock, self.connection:
            existing = self.connection.execute(
                "SELECT 1 FROM users WHERE email = ?",
                (email,),
            ).fetchone()
            if existing:
                raise ValueError("email_already_registered")
            user_count = self.connection.execute(
                "SELECT COUNT(*) FROM users"
            ).fetchone()[0]
            is_first_user = user_count == 0
            workspace_id = DEFAULT_WORKSPACE_ID if is_first_user else uuid4().hex
            workspace_name = "个人知识空间" if not is_first_user else "默认个人知识空间"
            self.connection.execute(
                """
                INSERT INTO users
                    (id, email, name, password_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    email,
                    request.name,
                    hash_password(request.password),
                    now,
                    now,
                ),
            )
            if is_first_user:
                self.connection.execute(
                    """
                    UPDATE workspaces
                    SET owner_user_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (user_id, now, workspace_id),
                )
            else:
                self.connection.execute(
                    """
                    INSERT INTO workspaces
                        (id, name, owner_user_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (workspace_id, workspace_name, user_id, now, now),
                )
            self.connection.execute(
                """
                INSERT INTO workspace_members
                    (workspace_id, user_id, role, created_at)
                VALUES (?, ?, 'owner', ?)
                """,
                (workspace_id, user_id, now),
            )
        result = self._new_session(
            user_id=user_id,
            workspace_id=workspace_id,
            ip_address=ip_address,
        )
        self.audit(
            workspace_id=workspace_id,
            user_id=user_id,
            action="auth.register",
            resource_type="user",
            resource_id=user_id,
            ip_address=ip_address,
        )
        return result

    def login(
        self,
        request: LoginRequest,
        *,
        ip_address: str | None = None,
    ) -> SessionResult:
        email = normalize_email(request.email)
        with self._lock:
            row = self.connection.execute(
                """
                SELECT u.*, wm.workspace_id, wm.role, w.name AS workspace_name
                FROM users u
                JOIN workspace_members wm ON wm.user_id = u.id
                JOIN workspaces w ON w.id = wm.workspace_id
                WHERE u.email = ? AND u.disabled = 0
                ORDER BY wm.created_at
                LIMIT 1
                """,
                (email,),
            ).fetchone()
        if row is None or not verify_password(
            request.password,
            row["password_hash"],
        ):
            raise ValueError("invalid_credentials")
        result = self._new_session(
            user_id=row["id"],
            workspace_id=row["workspace_id"],
            ip_address=ip_address,
        )
        self.audit(
            workspace_id=row["workspace_id"],
            user_id=row["id"],
            action="auth.login",
            resource_type="session",
            ip_address=ip_address,
        )
        return result

    def _new_session(
        self,
        *,
        user_id: str,
        workspace_id: str,
        ip_address: str | None,
    ) -> SessionResult:
        token = secrets.token_urlsafe(32)
        token_hash = _token_hash(token)
        now_dt = datetime.now(UTC)
        expires_dt = now_dt + self.session_ttl
        now = now_dt.isoformat()
        expires_at = expires_dt.isoformat()
        with self._lock, self.connection:
            row = self.connection.execute(
                """
                SELECT
                    u.id AS user_id, u.name AS user_name, u.email,
                    w.id AS workspace_id, w.name AS workspace_name,
                    wm.role
                FROM users u
                JOIN workspace_members wm ON wm.user_id = u.id
                JOIN workspaces w ON w.id = wm.workspace_id
                WHERE u.id = ? AND wm.workspace_id = ?
                """,
                (user_id, workspace_id),
            ).fetchone()
            if row is None:
                raise RuntimeError("workspace_membership_missing")
            self.connection.execute(
                """
                INSERT INTO auth_sessions
                    (token_hash, user_id, workspace_id, created_at,
                     last_seen_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    token_hash,
                    user_id,
                    workspace_id,
                    now,
                    now,
                    expires_at,
                ),
            )
            self.connection.execute(
                "UPDATE users SET updated_at = ? WHERE id = ?",
                (now, user_id),
            )
        identity = AuthIdentity(
            user=UserPublic(
                id=row["user_id"],
                name=row["user_name"],
                email=row["email"],
            ),
            workspace=WorkspacePublic(
                id=row["workspace_id"],
                name=row["workspace_name"],
                role=row["role"],
            ),
        )
        return SessionResult(
            identity=identity,
            token=token,
            expires_at=expires_dt,
            workspace_is_new=workspace_id != DEFAULT_WORKSPACE_ID,
        )

    def authenticate_token(self, token: str | None) -> AuthContext | None:
        if not token:
            return None
        token_hash = _token_hash(token)
        now = utc_now()
        with self._lock:
            row = self.connection.execute(
                """
                SELECT
                    s.token_hash, s.user_id, s.workspace_id,
                    u.name AS user_name, u.email,
                    w.name AS workspace_name, wm.role
                FROM auth_sessions s
                JOIN users u ON u.id = s.user_id
                JOIN workspaces w ON w.id = s.workspace_id
                JOIN workspace_members wm
                  ON wm.workspace_id = s.workspace_id
                 AND wm.user_id = s.user_id
                WHERE s.token_hash = ?
                  AND s.expires_at > ?
                  AND u.disabled = 0
                """,
                (token_hash, now),
            ).fetchone()
            if row is None:
                return None
            with self.connection:
                self.connection.execute(
                    "UPDATE auth_sessions SET last_seen_at = ? WHERE token_hash = ?",
                    (now, token_hash),
                )
        return AuthContext(
            user_id=row["user_id"],
            user_name=row["user_name"],
            email=row["email"],
            workspace_id=row["workspace_id"],
            workspace_name=row["workspace_name"],
            role=row["role"],
            session_hash=row["token_hash"],
        )

    def require_auth(self, request: Request) -> AuthContext:
        enforce_same_origin(request)
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            authorization = request.headers.get("authorization", "")
            if authorization.casefold().startswith("bearer "):
                token = authorization[7:].strip()
        context = self.authenticate_token(token)
        if context is None:
            raise HTTPException(
                status_code=401,
                detail="authentication_required",
            )
        request.state.auth = context
        return context

    def logout(self, token: str | None, context: AuthContext) -> None:
        if token:
            with self._lock, self.connection:
                self.connection.execute(
                    "DELETE FROM auth_sessions WHERE token_hash = ?",
                    (_token_hash(token),),
                )
        self.audit(
            workspace_id=context.workspace_id,
            user_id=context.user_id,
            action="auth.logout",
            resource_type="session",
        )

    def audit(
        self,
        *,
        workspace_id: str | None,
        user_id: str | None,
        action: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        metadata: dict | None = None,
        ip_address: str | None = None,
    ) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO audit_events
                    (workspace_id, user_id, action, resource_type,
                     resource_id, metadata_json, ip_address, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace_id,
                    user_id,
                    action,
                    resource_type,
                    resource_id,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    ip_address,
                    utc_now(),
                ),
            )
