from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .domain import utc_now
from .learning_domain import (
    ImportJob,
    ImportJobItem,
    ImportPreview,
    LearningConnection,
    PreviewCourse,
    PreviewFile,
    StoredConnection,
)


@dataclass(frozen=True)
class ScopedImportJob:
    workspace_id: str
    user_id: str
    job: ImportJob


def _parse_expiry(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("invalid_expiry") from None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class LearningStore:
    def __init__(self, db_path: Path, connector_key: bytes | None):
        if connector_key is not None and len(connector_key) != 32:
            raise ValueError("connector_key_must_be_32_bytes")
        self.db_path = db_path
        self.connector_key = connector_key
        self._lock = RLock()
        self._connection: sqlite3.Connection | None = None

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

                CREATE TABLE IF NOT EXISTS learning_connections (
                    provider TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    remote_nickname TEXT,
                    account_fingerprint TEXT,
                    status TEXT NOT NULL,
                    session_nonce BLOB,
                    session_ciphertext BLOB,
                    key_version INTEGER NOT NULL DEFAULT 1,
                    expires_at TEXT NOT NULL,
                    last_synced_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (workspace_id, user_id, provider)
                );

                CREATE TABLE IF NOT EXISTS learning_previews (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    archive_relpath TEXT,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS learning_preview_courses (
                    id TEXT NOT NULL,
                    preview_id TEXT NOT NULL
                        REFERENCES learning_previews(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    teacher TEXT NOT NULL DEFAULT '',
                    video_links_json TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    PRIMARY KEY (preview_id, id)
                );

                CREATE TABLE IF NOT EXISTS learning_preview_files (
                    id TEXT NOT NULL,
                    preview_id TEXT NOT NULL
                        REFERENCES learning_previews(id) ON DELETE CASCADE,
                    course_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    extension TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    remote_url TEXT,
                    archive_member TEXT,
                    supported INTEGER NOT NULL DEFAULT 1,
                    excluded_reason TEXT,
                    position INTEGER NOT NULL,
                    PRIMARY KEY (preview_id, id)
                );

                CREATE TABLE IF NOT EXISTS learning_import_jobs (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    preview_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    total_items INTEGER NOT NULL DEFAULT 0,
                    completed_items INTEGER NOT NULL DEFAULT 0,
                    failed_items INTEGER NOT NULL DEFAULT 0,
                    skipped_items INTEGER NOT NULL DEFAULT 0,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    error_code TEXT,
                    error_message TEXT
                );

                CREATE TABLE IF NOT EXISTS learning_import_items (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL
                        REFERENCES learning_import_jobs(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    external_course_id TEXT NOT NULL,
                    external_file_id TEXT,
                    target_course_id TEXT NOT NULL,
                    source_url TEXT,
                    archive_member TEXT,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    checksum TEXT,
                    asset_id TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_learning_jobs_workspace
                    ON learning_import_jobs(workspace_id, user_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_learning_items_job
                    ON learning_import_items(job_id, created_at);
                """
            )
            self._ensure_column(
                "learning_previews",
                "archive_relpath",
                "TEXT",
            )
            self._ensure_column(
                "learning_preview_files",
                "archive_member",
                "TEXT",
            )
            self._ensure_column(
                "learning_import_items",
                "archive_member",
                "TEXT",
            )

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("LearningStore is not initialized")
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _ensure_column(
        self,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {
            row["name"]
            for row in self.connection.execute(
                f"PRAGMA table_info({table})"
            ).fetchall()
        }
        if column not in columns:
            self.connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    def save_connection(
        self,
        *,
        workspace_id: str,
        user_id: str,
        remote_nickname: str | None,
        cookies: dict[str, str],
        expires_at: str,
        account_fingerprint: str | None = None,
    ) -> LearningConnection:
        expiry = _parse_expiry(expires_at)
        if expiry <= datetime.now(UTC):
            raise ValueError("invalid_expiry")
        nonce: bytes | None = None
        ciphertext: bytes | None = None
        if self.connector_key is not None:
            nonce = os.urandom(12)
            ciphertext = AESGCM(self.connector_key).encrypt(
                nonce,
                json.dumps(cookies, ensure_ascii=False).encode("utf-8"),
                None,
            )
        now = utc_now()
        with self._lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO learning_connections
                    (provider, workspace_id, user_id, remote_nickname,
                     account_fingerprint, status, session_nonce,
                     session_ciphertext, key_version, expires_at,
                     last_synced_at, created_at, updated_at)
                VALUES ('chaoxing', ?, ?, ?, ?, 'connected', ?, ?, 1, ?,
                        NULL, ?, ?)
                ON CONFLICT(workspace_id, user_id, provider) DO UPDATE SET
                    remote_nickname = excluded.remote_nickname,
                    account_fingerprint = excluded.account_fingerprint,
                    status = excluded.status,
                    session_nonce = excluded.session_nonce,
                    session_ciphertext = excluded.session_ciphertext,
                    key_version = excluded.key_version,
                    expires_at = excluded.expires_at,
                    updated_at = excluded.updated_at
                """,
                (
                    workspace_id,
                    user_id,
                    remote_nickname,
                    account_fingerprint,
                    nonce,
                    ciphertext,
                    expiry.isoformat(),
                    now,
                    now,
                ),
            )
        loaded = self.load_connection(workspace_id, user_id)
        if loaded is None:
            raise RuntimeError("connection_save_failed")
        return LearningConnection.model_validate(
            loaded.model_dump(exclude={"cookies", "account_fingerprint"})
        )

    def load_connection(
        self,
        workspace_id: str,
        user_id: str,
        provider: str = "chaoxing",
    ) -> StoredConnection | None:
        with self._lock:
            row = self.connection.execute(
                """
                SELECT * FROM learning_connections
                WHERE workspace_id = ? AND user_id = ? AND provider = ?
                """,
                (workspace_id, user_id, provider),
            ).fetchone()
        if row is None:
            return None
        base = StoredConnection(
            id=f"{workspace_id}:{user_id}:{provider}",
            provider="chaoxing",
            remote_nickname=row["remote_nickname"],
            account_fingerprint=row["account_fingerprint"],
            status=row["status"],
            expires_at=row["expires_at"],
            last_synced_at=row["last_synced_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            cookies=None,
        )
        try:
            expired = _parse_expiry(row["expires_at"]) <= datetime.now(UTC)
        except ValueError:
            expired = True
        if expired:
            self._set_connection_status(workspace_id, user_id, provider, "expired")
            return base.model_copy(update={"status": "expired", "cookies": None})
        if (
            self.connector_key is None
            or row["session_nonce"] is None
            or row["session_ciphertext"] is None
        ):
            self._set_connection_status(workspace_id, user_id, provider, "error")
            return base.model_copy(update={"status": "error", "cookies": None})
        try:
            plaintext = AESGCM(self.connector_key).decrypt(
                bytes(row["session_nonce"]),
                bytes(row["session_ciphertext"]),
                None,
            )
            cookies = json.loads(plaintext)
            if not isinstance(cookies, dict):
                raise ValueError("invalid_session_shape")
        except (InvalidTag, ValueError, TypeError, json.JSONDecodeError):
            self._set_connection_status(workspace_id, user_id, provider, "error")
            return base.model_copy(update={"status": "error", "cookies": None})
        return base.model_copy(update={"cookies": cookies, "status": "connected"})

    def touch_connection(
        self,
        workspace_id: str,
        user_id: str,
        provider: str = "chaoxing",
    ) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                """
                UPDATE learning_connections
                SET last_synced_at = ?, updated_at = ?
                WHERE workspace_id = ? AND user_id = ? AND provider = ?
                """,
                (utc_now(), utc_now(), workspace_id, user_id, provider),
            )

    def revoke_connection(
        self,
        workspace_id: str,
        user_id: str,
        provider: str = "chaoxing",
    ) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                """
                DELETE FROM learning_connections
                WHERE workspace_id = ? AND user_id = ? AND provider = ?
                """,
                (workspace_id, user_id, provider),
            )

    def _set_connection_status(
        self,
        workspace_id: str,
        user_id: str,
        provider: str,
        status: str,
    ) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                """
                UPDATE learning_connections
                SET status = ?, session_nonce = NULL,
                    session_ciphertext = NULL, updated_at = ?
                WHERE workspace_id = ? AND user_id = ? AND provider = ?
                """,
                (status, utc_now(), workspace_id, user_id, provider),
            )

    def create_preview(
        self,
        *,
        workspace_id: str,
        user_id: str,
        courses: list[PreviewCourse],
        expires_at: str,
        archive_relpath: str | None = None,
        preview_id: str | None = None,
    ) -> ImportPreview:
        expiry = _parse_expiry(expires_at)
        if expiry <= datetime.now(UTC):
            raise ValueError("invalid_expiry")
        preview_id = preview_id or uuid4().hex
        now = utc_now()
        with self._lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO learning_previews
                    (id, workspace_id, user_id, archive_relpath,
                     expires_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    preview_id,
                    workspace_id,
                    user_id,
                    archive_relpath,
                    expiry.isoformat(),
                    now,
                ),
            )
            for course_position, course in enumerate(courses):
                self.connection.execute(
                    """
                    INSERT INTO learning_preview_courses
                        (id, preview_id, workspace_id, user_id, external_id,
                         title, teacher, video_links_json, position)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        course.id,
                        preview_id,
                        workspace_id,
                        user_id,
                        course.id,
                        course.title,
                        course.teacher,
                        json.dumps(course.video_links, ensure_ascii=False),
                        course_position,
                    ),
                )
                for file_position, file in enumerate(course.documents):
                    self.connection.execute(
                        """
                        INSERT INTO learning_preview_files
                            (id, preview_id, course_id, workspace_id, user_id,
                             name, extension, size_bytes, remote_url,
                             archive_member, supported, excluded_reason,
                             position)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            file.id,
                            preview_id,
                            course.id,
                            workspace_id,
                            user_id,
                            file.name,
                            file.extension,
                            max(file.size_bytes, 0),
                            file.remote_url,
                            file.archive_member,
                            int(file.supported),
                            file.excluded_reason,
                            file_position,
                        ),
                    )
        loaded = self.get_preview(workspace_id, user_id, preview_id)
        if loaded is None:
            raise RuntimeError("preview_save_failed")
        return loaded

    def get_preview(
        self,
        workspace_id: str,
        user_id: str,
        preview_id: str,
    ) -> ImportPreview | None:
        with self._lock:
            preview = self.connection.execute(
                """
                SELECT * FROM learning_previews
                WHERE id = ? AND workspace_id = ? AND user_id = ?
                """,
                (preview_id, workspace_id, user_id),
            ).fetchone()
            if preview is None:
                return None
            course_rows = self.connection.execute(
                """
                SELECT * FROM learning_preview_courses
                WHERE preview_id = ? AND workspace_id = ? AND user_id = ?
                ORDER BY position
                """,
                (preview_id, workspace_id, user_id),
            ).fetchall()
            file_rows = self.connection.execute(
                """
                SELECT * FROM learning_preview_files
                WHERE preview_id = ? AND workspace_id = ? AND user_id = ?
                ORDER BY course_id, position
                """,
                (preview_id, workspace_id, user_id),
            ).fetchall()
        try:
            if _parse_expiry(preview["expires_at"]) <= datetime.now(UTC):
                return None
        except ValueError:
            return None
        by_course: dict[str, list[PreviewFile]] = {}
        for row in file_rows:
            by_course.setdefault(row["course_id"], []).append(
                PreviewFile(
                    id=row["id"],
                    name=row["name"],
                    extension=row["extension"],
                    size_bytes=row["size_bytes"],
                    supported=bool(row["supported"]),
                    excluded_reason=row["excluded_reason"],
                    remote_url=row["remote_url"],
                    archive_member=row["archive_member"],
                )
            )
        courses = [
            PreviewCourse(
                id=row["external_id"],
                title=row["title"],
                teacher=row["teacher"],
                documents=by_course.get(row["id"], []),
                video_links=json.loads(row["video_links_json"]),
            )
            for row in course_rows
        ]
        return ImportPreview(
            id=preview["id"],
            courses=courses,
            total_documents=sum(len(course.documents) for course in courses),
            total_video_links=sum(len(course.video_links) for course in courses),
            total_bytes=sum(
                file.size_bytes
                for course in courses
                for file in course.documents
                if file.supported
            ),
            generated_at=preview["created_at"],
            expires_at=preview["expires_at"],
            archive_relpath=preview["archive_relpath"],
        )

    def create_job(
        self,
        *,
        workspace_id: str,
        user_id: str,
        preview_id: str,
        total_items: int,
        items: list[ImportJobItem],
    ) -> ImportJob:
        job_id = uuid4().hex
        now = utc_now()
        with self._lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO learning_import_jobs
                    (id, workspace_id, user_id, preview_id, status, progress,
                     total_items, completed_items, failed_items, skipped_items,
                     cancel_requested, created_at)
                VALUES (?, ?, ?, ?, 'queued', 0, ?, 0, 0, 0, 0, ?)
                """,
                (
                    job_id,
                    workspace_id,
                    user_id,
                    preview_id,
                    total_items,
                    now,
                ),
            )
            for item in items:
                self.connection.execute(
                    """
                    INSERT INTO learning_import_items
                        (id, job_id, workspace_id, user_id, kind, title,
                         external_course_id, external_file_id,
                         target_course_id, source_url, archive_member,
                         size_bytes, status, attempts, checksum, asset_id,
                         error_code, error_message, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.id,
                        job_id,
                        workspace_id,
                        user_id,
                        item.kind,
                        item.title,
                        item.external_course_id,
                        item.external_file_id,
                        item.target_course_id,
                        item.source_url,
                        item.archive_member,
                        max(item.size_bytes, 0),
                        item.status,
                        item.attempts,
                        item.checksum,
                        item.asset_id,
                        item.error_code,
                        item.error_message,
                        now,
                        now,
                    ),
                )
        job = self.get_job(workspace_id, user_id, job_id)
        if job is None:
            raise RuntimeError("job_save_failed")
        return job

    def get_job(
        self,
        workspace_id: str,
        user_id: str,
        job_id: str,
    ) -> ImportJob | None:
        with self._lock:
            row = self.connection.execute(
                """
                SELECT * FROM learning_import_jobs
                WHERE id = ? AND workspace_id = ? AND user_id = ?
                """,
                (job_id, workspace_id, user_id),
            ).fetchone()
        return self._job_from_row(row) if row else None

    def list_jobs(
        self,
        workspace_id: str,
        user_id: str,
        *,
        limit: int = 20,
    ) -> list[ImportJob]:
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT * FROM learning_import_jobs
                WHERE workspace_id = ? AND user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (workspace_id, user_id, max(1, min(limit, 100))),
            ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def list_runnable_jobs(self, *, limit: int = 10) -> list[ScopedImportJob]:
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT * FROM learning_import_jobs
                WHERE status = 'queued'
                ORDER BY created_at
                LIMIT ?
                """,
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [
            ScopedImportJob(
                workspace_id=row["workspace_id"],
                user_id=row["user_id"],
                job=self._job_from_row(row),
            )
            for row in rows
        ]

    def recover_interrupted_jobs(self) -> int:
        with self._lock, self.connection:
            result = self.connection.execute(
                """
                UPDATE learning_import_jobs
                SET status = 'queued', started_at = NULL
                WHERE status IN ('reading', 'downloading', 'parsing')
                """
            )
        return result.rowcount

    def claim_job(
        self,
        workspace_id: str,
        user_id: str,
        job_id: str,
    ) -> ImportJob | None:
        now = utc_now()
        with self._lock, self.connection:
            result = self.connection.execute(
                """
                UPDATE learning_import_jobs
                SET status = 'reading',
                    started_at = ?,
                    error_code = NULL,
                    error_message = NULL
                WHERE id = ?
                  AND workspace_id = ?
                  AND user_id = ?
                  AND status = 'queued'
                """,
                (now, job_id, workspace_id, user_id),
            )
        if result.rowcount == 0:
            return None
        return self.get_job(workspace_id, user_id, job_id)

    def expire_online_jobs(self, workspace_id: str, user_id: str) -> int:
        with self._lock, self.connection:
            result = self.connection.execute(
                """
                UPDATE learning_import_jobs
                SET status = 'session_expired',
                    error_code = 'session_expired',
                    error_message = '学习通连接已断开，请重新扫码后重试。',
                    finished_at = ?
                WHERE workspace_id = ?
                  AND user_id = ?
                  AND status IN ('queued', 'reading', 'downloading', 'parsing')
                  AND preview_id IN (
                      SELECT id FROM learning_previews
                      WHERE archive_relpath IS NULL
                  )
                """,
                (utc_now(), workspace_id, user_id),
            )
        return result.rowcount

    def list_expired_zip_archives(self) -> list[sqlite3.Row]:
        with self._lock:
            return self.connection.execute(
                """
                SELECT id, workspace_id, user_id, archive_relpath
                FROM learning_previews
                WHERE archive_relpath IS NOT NULL
                  AND expires_at <= ?
                """,
                (utc_now(),),
            ).fetchall()

    def get_preview_archive_relpath(
        self,
        workspace_id: str,
        user_id: str,
        preview_id: str,
    ) -> str | None:
        with self._lock:
            row = self.connection.execute(
                """
                SELECT archive_relpath
                FROM learning_previews
                WHERE id = ? AND workspace_id = ? AND user_id = ?
                """,
                (preview_id, workspace_id, user_id),
            ).fetchone()
        return row["archive_relpath"] if row else None

    def update_job(
        self,
        *,
        workspace_id: str,
        user_id: str,
        job_id: str,
        **updates,
    ) -> ImportJob | None:
        allowed = {
            "status",
            "progress",
            "total_items",
            "completed_items",
            "failed_items",
            "skipped_items",
            "cancel_requested",
            "started_at",
            "finished_at",
            "error_code",
            "error_message",
        }
        selected = {key: value for key, value in updates.items() if key in allowed}
        if selected:
            assignments = ", ".join(f"{key} = ?" for key in selected)
            values = [
                int(value) if isinstance(value, bool) else value
                for value in selected.values()
            ]
            values.extend((job_id, workspace_id, user_id))
            with self._lock, self.connection:
                self.connection.execute(
                    f"""
                    UPDATE learning_import_jobs SET {assignments}
                    WHERE id = ? AND workspace_id = ? AND user_id = ?
                    """,
                    values,
                )
        return self.get_job(workspace_id, user_id, job_id)

    def list_job_items(
        self,
        workspace_id: str,
        user_id: str,
        job_id: str,
    ) -> list[ImportJobItem]:
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT * FROM learning_import_items
                WHERE job_id = ? AND workspace_id = ? AND user_id = ?
                ORDER BY created_at, rowid
                """,
                (job_id, workspace_id, user_id),
            ).fetchall()
        return [self._item_from_row(row) for row in rows]

    def update_job_item(
        self,
        *,
        workspace_id: str,
        user_id: str,
        job_id: str,
        item_id: str,
        **updates,
    ) -> ImportJobItem | None:
        allowed = {
            "status",
            "attempts",
            "checksum",
            "asset_id",
            "error_code",
            "error_message",
        }
        selected = {key: value for key, value in updates.items() if key in allowed}
        if selected:
            selected["updated_at"] = utc_now()
            assignments = ", ".join(f"{key} = ?" for key in selected)
            values = list(selected.values())
            values.extend((item_id, job_id, workspace_id, user_id))
            with self._lock, self.connection:
                self.connection.execute(
                    f"""
                    UPDATE learning_import_items SET {assignments}
                    WHERE id = ? AND job_id = ? AND workspace_id = ? AND user_id = ?
                    """,
                    values,
                )
        with self._lock:
            row = self.connection.execute(
                """
                SELECT * FROM learning_import_items
                WHERE id = ? AND job_id = ? AND workspace_id = ? AND user_id = ?
                """,
                (item_id, job_id, workspace_id, user_id),
            ).fetchone()
        return self._item_from_row(row) if row else None

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> ImportJob:
        return ImportJob(
            id=row["id"],
            preview_id=row["preview_id"],
            status=row["status"],
            progress=row["progress"],
            total_items=row["total_items"],
            completed_items=row["completed_items"],
            failed_items=row["failed_items"],
            skipped_items=row["skipped_items"],
            cancel_requested=bool(row["cancel_requested"]),
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            error_code=row["error_code"],
            error_message=row["error_message"],
        )

    @staticmethod
    def _item_from_row(row: sqlite3.Row) -> ImportJobItem:
        return ImportJobItem(
            id=row["id"],
            job_id=row["job_id"],
            kind=row["kind"],
            title=row["title"],
            external_course_id=row["external_course_id"],
            external_file_id=row["external_file_id"],
            target_course_id=row["target_course_id"],
            source_url=row["source_url"],
            archive_member=row["archive_member"],
            size_bytes=row["size_bytes"],
            status=row["status"],
            attempts=row["attempts"],
            checksum=row["checksum"],
            asset_id=row["asset_id"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
