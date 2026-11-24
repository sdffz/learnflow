from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from collections import Counter
from pathlib import Path
from threading import RLock
from uuid import uuid4

from .domain import utc_now
from .ingestion import (
    KnowledgeChunkDraft,
    TextExtraction,
    build_knowledge,
    extract_text,
)
from .knowledge_domain import (
    AssetDetail,
    Course,
    CourseCreate,
    CourseUpdate,
    KnowledgeAsset,
    KnowledgeChunk,
    KnowledgeOverview,
    KnowledgeSearchResponse,
    NoteCreate,
    excerpt,
    normalize_tags,
)
from .tenancy import DEFAULT_WORKSPACE_ID

DEFAULT_MAX_WORKSPACE_BYTES = 500 * 1024 * 1024
DEFAULT_MAX_WORKSPACE_ASSETS = 500


class KnowledgeStore:
    def __init__(
        self,
        db_path: Path,
        upload_dir: Path,
        seed_dir: Path | None = None,
        max_workspace_bytes: int = DEFAULT_MAX_WORKSPACE_BYTES,
        max_workspace_assets: int = DEFAULT_MAX_WORKSPACE_ASSETS,
    ):
        self.db_path = db_path
        self.upload_dir = upload_dir
        self.seed_dir = seed_dir
        self.max_workspace_bytes = max_workspace_bytes
        self.max_workspace_assets = max_workspace_assets
        self._lock = RLock()
        self._connection: sqlite3.Connection | None = None

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._lock, self.connection:
            self.connection.executescript(
                """
                PRAGMA foreign_keys = ON;
                PRAGMA journal_mode = WAL;
                PRAGMA synchronous = NORMAL;
                PRAGMA busy_timeout = 5000;

                CREATE TABLE IF NOT EXISTS courses (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    color TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledge_assets (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    original_name TEXT,
                    mime_type TEXT,
                    file_relpath TEXT,
                    status TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL,
                    error TEXT,
                    external_source TEXT,
                    external_id TEXT,
                    source_url TEXT,
                    checksum TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    id TEXT PRIMARY KEY,
                    asset_id TEXT NOT NULL REFERENCES knowledge_assets(id) ON DELETE CASCADE,
                    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    excerpt TEXT NOT NULL,
                    search_text TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_courses_workspace
                    ON courses(workspace_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_assets_course
                    ON knowledge_assets(course_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_chunks_asset
                    ON knowledge_chunks(asset_id);
                CREATE INDEX IF NOT EXISTS idx_chunks_course
                    ON knowledge_chunks(course_id, created_at);

                CREATE TABLE IF NOT EXISTS knowledge_seed_markers (
                    key TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(
                "knowledge_assets",
                "size_bytes",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column("knowledge_assets", "external_source", "TEXT")
            self._ensure_column("knowledge_assets", "external_id", "TEXT")
            self._ensure_column("knowledge_assets", "source_url", "TEXT")
            self._ensure_column("knowledge_assets", "checksum", "TEXT")
            self.connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_external
                ON knowledge_assets(workspace_id, external_source, external_id)
                WHERE external_source IS NOT NULL AND external_id IS NOT NULL
                """
            )
            count = self.connection.execute(
                "SELECT COUNT(*) FROM courses WHERE workspace_id = ?",
                (DEFAULT_WORKSPACE_ID,),
            ).fetchone()[0]
            seeded_course_id: str | None = None
            if count == 0:
                seeded_course_id = self._insert_course(
                    CourseCreate(
                        title="人工智能导论",
                        description="示例课程：AI 基础、搜索、机器学习、神经网络与伦理",
                    ),
                    DEFAULT_WORKSPACE_ID,
                )
            else:
                row = self.connection.execute(
                    """
                    SELECT id FROM courses
                    WHERE workspace_id = ? AND title = '人工智能导论'
                    ORDER BY created_at
                    LIMIT 1
                    """,
                    (DEFAULT_WORKSPACE_ID,),
                ).fetchone()
                if row:
                    seeded_course_id = row["id"]
        if seeded_course_id:
            self._seed_example_assets(seeded_course_id, DEFAULT_WORKSPACE_ID)

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("KnowledgeStore is not initialized")
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def ensure_workspace(
        self,
        workspace_id: str,
        *,
        title: str = "我的知识文件夹",
    ) -> Course:
        courses = self.list_courses(workspace_id)
        if courses:
            return courses[0]
        return self.create_course(
            CourseCreate(
                title=title,
                description="用于整理个人资料、照片、笔记和知识点",
            ),
            workspace_id,
        )

    def create_course(
        self,
        request: CourseCreate,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> Course:
        with self._lock, self.connection:
            course_id = self._insert_course(request, workspace_id)
        course = self.get_course(course_id, workspace_id)
        if course is None:
            raise RuntimeError("course_insert_failed")
        return course

    def _seed_example_assets(
        self,
        course_id: str,
        workspace_id: str,
    ) -> None:
        if self.seed_dir is None or not self.seed_dir.is_dir():
            return
        marker_key = "ai_intro_v3"
        with self._lock:
            marker = self.connection.execute(
                "SELECT 1 FROM knowledge_seed_markers WHERE key = ?",
                (marker_key,),
            ).fetchone()
        if marker is not None:
            return

        seed_names = [path.name for path in sorted(self.seed_dir.glob("*.md"))]
        with self._lock, self.connection:
            for name in seed_names:
                row = self.connection.execute(
                    """
                    SELECT id, file_relpath FROM knowledge_assets
                    WHERE course_id = ? AND original_name = ?
                      AND file_relpath LIKE 'seed/%'
                    """,
                    (course_id, name),
                ).fetchone()
                if row:
                    self.connection.execute(
                        "DELETE FROM knowledge_assets WHERE id = ?",
                        (row["id"],),
                    )
                    if row["file_relpath"]:
                        self._unlink_relpath(row["file_relpath"])

        for source in sorted(self.seed_dir.glob("*.md")):
            try:
                raw_text = source.read_text(encoding="utf-8")
                text = extract_text(source, "text/markdown").text
                frontmatter_title = re.search(
                    r"(?m)^title:\s*(.+?)\s*$",
                    raw_text,
                )
                heading = re.search(r"(?m)^#\s+(.+?)\s*$", text)
                title = (
                    frontmatter_title.group(1).strip()
                    if frontmatter_title
                    else (heading.group(1).strip() if heading else source.stem)
                )
                relative = Path("seed") / f"{uuid4().hex}{source.suffix}"
                destination = self.upload_dir / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                self.create_asset(
                    course_id=course_id,
                    workspace_id=workspace_id,
                    kind="file",
                    title=title,
                    original_name=source.name,
                    mime_type="text/markdown",
                    file_relpath=str(relative),
                    extraction=TextExtraction(text=text, status="ready"),
                    tags=["人工智能", "示例资料"],
                    size_bytes=source.stat().st_size,
                )
            except Exception:
                continue
        with self._lock, self.connection:
            self.connection.execute(
                """
                INSERT OR IGNORE INTO knowledge_seed_markers (key, created_at)
                VALUES (?, ?)
                """,
                (marker_key, utc_now()),
            )

    def _insert_course(
        self,
        request: CourseCreate,
        workspace_id: str,
    ) -> str:
        course_id = uuid4().hex
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO courses
                (id, workspace_id, title, description, color, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                course_id,
                workspace_id,
                request.title,
                request.description,
                request.color,
                now,
                now,
            ),
        )
        return course_id

    def get_course(
        self,
        course_id: str,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> Course | None:
        with self._lock:
            row = self.connection.execute(
                self._course_select() + " WHERE c.id = ? AND c.workspace_id = ?",
                (course_id, workspace_id),
            ).fetchone()
        return self._course_from_row(row) if row else None

    def list_courses(
        self,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> list[Course]:
        with self._lock:
            rows = self.connection.execute(
                self._course_select()
                + " WHERE c.workspace_id = ? ORDER BY c.updated_at DESC",
                (workspace_id,),
            ).fetchall()
        return [self._course_from_row(row) for row in rows]

    def update_course(
        self,
        course_id: str,
        request: CourseUpdate,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> Course:
        updates: list[str] = []
        values: list[str] = []
        for field, value in (
            ("title", request.title),
            ("description", request.description),
            ("color", request.color),
        ):
            if value is not None:
                updates.append(f"{field} = ?")
                values.append(value)
        if updates:
            updates.append("updated_at = ?")
            values.append(utc_now())
            values.append(course_id)
            values.append(workspace_id)
            with self._lock, self.connection:
                result = self.connection.execute(
                    f"UPDATE courses SET {', '.join(updates)} WHERE id = ? AND workspace_id = ?",
                    values,
                )
            if result.rowcount == 0:
                raise KeyError(course_id)
        course = self.get_course(course_id, workspace_id)
        if course is None:
            raise KeyError(course_id)
        return course

    def delete_course(
        self,
        course_id: str,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> None:
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT file_relpath FROM knowledge_assets
                WHERE course_id = ? AND workspace_id = ?
                """,
                (course_id, workspace_id),
            ).fetchall()
            with self.connection:
                result = self.connection.execute(
                    "DELETE FROM courses WHERE id = ? AND workspace_id = ?",
                    (course_id, workspace_id),
                )
        if result.rowcount == 0:
            raise KeyError(course_id)
        for row in rows:
            if row["file_relpath"]:
                self._unlink_relpath(row["file_relpath"])

    def create_note(
        self,
        course_id: str,
        request: NoteCreate,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> KnowledgeAsset:
        return self.create_asset(
            course_id=course_id,
            workspace_id=workspace_id,
            kind="note",
            title=request.title,
            original_name=None,
            mime_type=None,
            file_relpath=None,
            extraction=TextExtraction(text=request.content, status="ready"),
            tags=request.tags,
            size_bytes=len(request.content.encode("utf-8")),
        )

    def create_asset(
        self,
        *,
        course_id: str,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
        kind: str,
        title: str,
        original_name: str | None,
        mime_type: str | None,
        file_relpath: str | None,
        extraction: TextExtraction,
        tags: list[str],
        size_bytes: int = 0,
        external_source: str | None = None,
        external_id: str | None = None,
        source_url: str | None = None,
        checksum: str | None = None,
    ) -> KnowledgeAsset:
        course = self.get_course(course_id, workspace_id)
        if course is None:
            raise KeyError(course_id)

        normalized_title = title.strip() or original_name or "未命名资料"
        normalized_tags = normalize_tags(tags)
        with self._lock:
            usage = self.connection.execute(
                """
                SELECT COUNT(*) AS asset_count,
                       COALESCE(SUM(size_bytes), 0) AS total_bytes
                FROM knowledge_assets
                WHERE workspace_id = ?
                """,
                (workspace_id,),
            ).fetchone()
        if (
            usage["asset_count"] >= self.max_workspace_assets
            or usage["total_bytes"] + max(size_bytes, 0)
            > self.max_workspace_bytes
        ):
            raise ValueError("workspace_quota_exceeded")
        chunks = self._chunks_for_asset(
            title=normalized_title,
            tags=normalized_tags,
            extraction=extraction,
            kind=kind,
        )

        asset_id = uuid4().hex
        now = utc_now()
        summary = excerpt(extraction.text) if extraction.text else chunks[0].excerpt
        with self._lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO knowledge_assets
                    (id, workspace_id, course_id, kind, title, original_name,
                     mime_type, file_relpath, status, content, summary, tags_json,
                     size_bytes, error, external_source, external_id, source_url,
                     checksum, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset_id,
                    workspace_id,
                    course_id,
                    kind,
                    normalized_title,
                    original_name,
                    mime_type,
                    file_relpath,
                    extraction.status,
                    extraction.text,
                    summary,
                    json.dumps(normalized_tags, ensure_ascii=False),
                    max(size_bytes, 0),
                    extraction.error,
                    external_source,
                    external_id,
                    source_url,
                    checksum,
                    now,
                    now,
                ),
            )
            self._insert_chunks(
                asset_id=asset_id,
                course_id=course_id,
                chunks=chunks,
                created_at=now,
            )
            self.connection.execute(
                """
                UPDATE courses SET updated_at = ?
                WHERE id = ? AND workspace_id = ?
                """,
                (now, course_id, workspace_id),
            )
        asset = self.get_asset(asset_id, workspace_id)
        if asset is None:
            raise RuntimeError("asset_insert_failed")
        return KnowledgeAsset.model_validate(asset.model_dump(exclude={"chunks"}))

    def upsert_external_asset(
        self,
        *,
        course_id: str,
        workspace_id: str,
        external_source: str,
        external_id: str,
        source_url: str | None,
        checksum: str | None,
        title: str,
        original_name: str | None,
        mime_type: str | None,
        file_relpath: str | None,
        extraction: TextExtraction,
        tags: list[str],
        size_bytes: int,
        kind: str = "file",
    ) -> tuple[KnowledgeAsset, bool]:
        course = self.get_course(course_id, workspace_id)
        if course is None:
            raise KeyError("course_not_found")
        with self._lock:
            existing = self.connection.execute(
                """
                SELECT id, file_relpath, checksum, size_bytes
                FROM knowledge_assets
                WHERE workspace_id = ?
                  AND external_source = ?
                  AND external_id = ?
                """,
                (workspace_id, external_source, external_id),
            ).fetchone()
            usage = self.connection.execute(
                """
                SELECT COUNT(*) AS asset_count,
                       COALESCE(SUM(size_bytes), 0) AS total_bytes
                FROM knowledge_assets
                WHERE workspace_id = ?
                """,
                (workspace_id,),
            ).fetchone()
        if existing is not None and existing["checksum"] == checksum:
            if file_relpath and file_relpath != existing["file_relpath"]:
                self._unlink_relpath(file_relpath)
            current = self.get_asset(existing["id"], workspace_id)
            if current is None:
                raise RuntimeError("asset_lookup_failed")
            return (
                KnowledgeAsset.model_validate(current.model_dump(exclude={"chunks"})),
                False,
            )

        existing_count = 1 if existing is not None else 0
        existing_bytes = existing["size_bytes"] if existing is not None else 0
        if (
            usage["asset_count"] - existing_count >= self.max_workspace_assets
            or usage["total_bytes"] - existing_bytes + max(size_bytes, 0)
            > self.max_workspace_bytes
        ):
            raise ValueError("workspace_quota_exceeded")

        normalized_title = title.strip() or original_name or "未命名资料"
        normalized_tags = normalize_tags(tags)
        chunks = self._chunks_for_asset(
            title=normalized_title,
            tags=normalized_tags,
            extraction=extraction,
            kind=kind,
        )
        summary = excerpt(extraction.text) if extraction.text else chunks[0].excerpt
        now = utc_now()
        old_relpath: str | None = None
        created = existing is None
        if existing is None:
            asset_id = uuid4().hex
        else:
            asset_id = existing["id"]
            old_relpath = existing["file_relpath"]
        with self._lock, self.connection:
            if existing is None:
                self.connection.execute(
                    """
                    INSERT INTO knowledge_assets
                        (id, workspace_id, course_id, kind, title, original_name,
                         mime_type, file_relpath, status, content, summary,
                         tags_json, size_bytes, error, external_source,
                         external_id, source_url, checksum, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        asset_id,
                        workspace_id,
                        course_id,
                        kind,
                        normalized_title,
                        original_name,
                        mime_type,
                        file_relpath,
                        extraction.status,
                        extraction.text,
                        summary,
                        json.dumps(normalized_tags, ensure_ascii=False),
                        max(size_bytes, 0),
                        extraction.error,
                        external_source,
                        external_id,
                        source_url,
                        checksum,
                        now,
                        now,
                    ),
                )
            else:
                self.connection.execute(
                    """
                    UPDATE knowledge_assets
                    SET course_id = ?, kind = ?, title = ?, original_name = ?,
                        mime_type = ?, file_relpath = ?, status = ?, content = ?,
                        summary = ?, tags_json = ?, size_bytes = ?, error = ?,
                        source_url = ?, checksum = ?, updated_at = ?
                    WHERE id = ? AND workspace_id = ?
                    """,
                    (
                        course_id,
                        kind,
                        normalized_title,
                        original_name,
                        mime_type,
                        file_relpath,
                        extraction.status,
                        extraction.text,
                        summary,
                        json.dumps(normalized_tags, ensure_ascii=False),
                        max(size_bytes, 0),
                        extraction.error,
                        source_url,
                        checksum,
                        now,
                        asset_id,
                        workspace_id,
                    ),
                )
                self.connection.execute(
                    "DELETE FROM knowledge_chunks WHERE asset_id = ?",
                    (asset_id,),
                )
            self._insert_chunks(
                asset_id=asset_id,
                course_id=course_id,
                chunks=chunks,
                created_at=now,
            )
            self.connection.execute(
                """
                UPDATE courses SET updated_at = ?
                WHERE id = ? AND workspace_id = ?
                """,
                (now, course_id, workspace_id),
            )
        if old_relpath and old_relpath != file_relpath:
            self._unlink_relpath(old_relpath)
        asset = self.get_asset(asset_id, workspace_id)
        if asset is None:
            raise RuntimeError("asset_upsert_failed")
        return (
            KnowledgeAsset.model_validate(asset.model_dump(exclude={"chunks"})),
            created,
        )

    def upsert_external_note(
        self,
        *,
        course_id: str,
        workspace_id: str,
        external_source: str,
        external_id: str,
        title: str,
        content: str,
        tags: list[str],
    ) -> tuple[KnowledgeAsset, bool]:
        return self.upsert_external_asset(
            course_id=course_id,
            workspace_id=workspace_id,
            external_source=external_source,
            external_id=external_id,
            source_url=None,
            checksum=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            title=title,
            original_name=None,
            mime_type=None,
            file_relpath=None,
            extraction=TextExtraction(text=content, status="ready"),
            tags=tags,
            size_bytes=len(content.encode("utf-8")),
            kind="note",
        )

    def list_assets(
        self,
        course_id: str,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> list[KnowledgeAsset]:
        if self.get_course(course_id, workspace_id) is None:
            raise KeyError(course_id)
        with self._lock:
            rows = self.connection.execute(
                self._asset_select()
                + """
                WHERE a.course_id = ? AND a.workspace_id = ?
                ORDER BY a.created_at DESC
                """,
                (course_id, workspace_id),
            ).fetchall()
        return [self._asset_from_row(row) for row in rows]

    def get_asset(
        self,
        asset_id: str,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> AssetDetail | None:
        with self._lock:
            row = self.connection.execute(
                self._asset_select() + " WHERE a.id = ? AND a.workspace_id = ?",
                (asset_id, workspace_id),
            ).fetchone()
            if row is None:
                return None
            chunk_rows = self.connection.execute(
                self._chunk_select()
                + """
                WHERE c.asset_id = ? AND a.workspace_id = ?
                ORDER BY c.rowid
                """,
                (asset_id, workspace_id),
            ).fetchall()
        asset = self._asset_from_row(row)
        file_available = bool(
            row["file_relpath"] and self._safe_path(row["file_relpath"]).is_file()
        )
        return AssetDetail(
            **asset.model_dump(),
            chunks=[self._chunk_from_row(item) for item in chunk_rows],
            file_available=file_available,
        )

    def delete_asset(
        self,
        asset_id: str,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> None:
        with self._lock:
            row = self.connection.execute(
                "SELECT file_relpath FROM knowledge_assets WHERE id = ? AND workspace_id = ?",
                (asset_id, workspace_id),
            ).fetchone()
            if row is None:
                raise KeyError(asset_id)
            with self.connection:
                self.connection.execute(
                    "DELETE FROM knowledge_assets WHERE id = ? AND workspace_id = ?",
                    (asset_id, workspace_id),
                )
        if row["file_relpath"]:
            self._unlink_relpath(row["file_relpath"])

    def asset_file(
        self,
        asset_id: str,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> tuple[Path, str, str | None] | None:
        with self._lock:
            row = self.connection.execute(
                """
                SELECT file_relpath, mime_type, original_name
                FROM knowledge_assets
                WHERE id = ? AND workspace_id = ?
                """,
                (asset_id, workspace_id),
            ).fetchone()
        if row is None or not row["file_relpath"]:
            return None
        path = self._safe_path(row["file_relpath"])
        if not path.is_file():
            return None
        return (
            path,
            row["mime_type"] or "application/octet-stream",
            row["original_name"],
        )

    def search(
        self,
        query: str,
        tag: str = "",
        course_id: str = "",
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> KnowledgeSearchResponse:
        query_value = " ".join(query.split()).casefold()
        tag_value = tag.strip().casefold()
        course_value = course_id.strip()
        with self._lock:
            rows = self.connection.execute(
                self._chunk_select()
                + """
                WHERE a.workspace_id = ?
                  AND (? = '' OR c.course_id = ?)
                  AND (
                    ? = ''
                    OR lower(
                      c.search_text || ' ' || a.title || ' ' ||
                      a.content || ' ' || co.title || ' ' || a.tags_json
                    ) LIKE ?
                  )
                  AND (? = '' OR lower(a.tags_json) LIKE ?)
                ORDER BY c.created_at DESC
                LIMIT 100
                """,
                (
                    workspace_id,
                    course_value,
                    course_value,
                    query_value,
                    f"%{query_value}%",
                    tag_value,
                    f"%{tag_value}%",
                ),
            ).fetchall()
        items = [self._chunk_from_row(row) for row in rows]
        unique: list[KnowledgeChunk] = []
        seen: set[str] = set()
        for item in items:
            if item.id not in seen:
                seen.add(item.id)
                unique.append(item)
        return KnowledgeSearchResponse(items=unique, total=len(unique))

    def overview(
        self,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> KnowledgeOverview:
        courses = self.list_courses(workspace_id)
        with self._lock:
            asset_count = self.connection.execute(
                "SELECT COUNT(*) FROM knowledge_assets WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()[0]
            knowledge_count = self.connection.execute(
                """
                SELECT COUNT(*)
                FROM knowledge_chunks c
                JOIN knowledge_assets a ON a.id = c.asset_id
                WHERE a.workspace_id = ?
                """,
                (workspace_id,),
            ).fetchone()[0]
            pending_count = self.connection.execute(
                """
                SELECT COUNT(*)
                FROM knowledge_assets
                WHERE workspace_id = ? AND status IN ('processing', 'failed')
                """,
                (workspace_id,),
            ).fetchone()[0]
            recent_rows = self.connection.execute(
                self._asset_select()
                + """
                WHERE a.workspace_id = ?
                ORDER BY a.created_at DESC
                LIMIT 6
                """,
                (workspace_id,),
            ).fetchall()
            tag_rows = self.connection.execute(
                "SELECT tags_json FROM knowledge_assets WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchall()
        tag_counts: Counter[str] = Counter()
        display_tags: dict[str, str] = {}
        for row in tag_rows:
            for value in json.loads(row["tags_json"]):
                key = value.casefold()
                tag_counts[key] += 1
                display_tags.setdefault(key, value)
        return KnowledgeOverview(
            course_count=len(courses),
            asset_count=asset_count,
            knowledge_count=knowledge_count,
            pending_count=pending_count,
            recent_assets=[self._asset_from_row(row) for row in recent_rows],
            courses=courses,
            top_tags=[display_tags[key] for key, _count in tag_counts.most_common(10)],
        )

    @staticmethod
    def _chunks_for_asset(
        *,
        title: str,
        tags: list[str],
        extraction: TextExtraction,
        kind: str,
    ) -> list[KnowledgeChunkDraft]:
        chunks = build_knowledge(extraction.text, title, tags)
        if chunks:
            return chunks
        placeholder = f"图片资料：{title}" if kind == "image" else f"资料：{title}"
        return [
            KnowledgeChunkDraft(
                title=title[:80],
                excerpt=placeholder,
                search_text=f"{title}\n{placeholder}\n{' '.join(tags)}",
                tags=tags,
            )
        ]

    def _insert_chunks(
        self,
        *,
        asset_id: str,
        course_id: str,
        chunks: list[KnowledgeChunkDraft],
        created_at: str,
    ) -> None:
        for chunk in chunks:
            self.connection.execute(
                """
                INSERT INTO knowledge_chunks
                    (id, asset_id, course_id, title, excerpt, search_text,
                     tags_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    asset_id,
                    course_id,
                    chunk.title,
                    chunk.excerpt,
                    chunk.search_text,
                    json.dumps(chunk.tags, ensure_ascii=False),
                    created_at,
                ),
            )

    def _safe_path(self, relpath: str) -> Path:
        root = self.upload_dir.resolve()
        path = (self.upload_dir / relpath).resolve()
        if root not in path.parents and path != root:
            raise ValueError("invalid_file_path")
        return path

    def _unlink_relpath(self, relpath: str) -> None:
        try:
            path = self._safe_path(relpath)
            path.unlink(missing_ok=True)
        except (OSError, ValueError):
            return

    @staticmethod
    def _course_select() -> str:
        return """
            SELECT
                c.*,
                (SELECT COUNT(*) FROM knowledge_assets a WHERE a.course_id = c.id)
                    AS asset_count,
                (SELECT COUNT(*) FROM knowledge_chunks k WHERE k.course_id = c.id)
                    AS knowledge_count
            FROM courses c
        """

    @staticmethod
    def _asset_select() -> str:
        return """
            SELECT
                a.*,
                c.title AS course_title,
                (
                    SELECT COUNT(*)
                    FROM knowledge_chunks k
                    WHERE k.asset_id = a.id
                ) AS knowledge_count
            FROM knowledge_assets a
            JOIN courses c ON c.id = a.course_id
        """

    @staticmethod
    def _chunk_select() -> str:
        return """
            SELECT
                c.id,
                c.asset_id,
                a.title AS asset_title,
                c.course_id,
                co.title AS course_title,
                c.title,
                c.excerpt,
                c.tags_json
            FROM knowledge_chunks c
            JOIN knowledge_assets a ON a.id = c.asset_id
            JOIN courses co ON co.id = c.course_id
        """

    @staticmethod
    def _course_from_row(row: sqlite3.Row) -> Course:
        return Course(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            color=row["color"],
            asset_count=row["asset_count"],
            knowledge_count=row["knowledge_count"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _asset_from_row(row: sqlite3.Row) -> KnowledgeAsset:
        return KnowledgeAsset(
            id=row["id"],
            course_id=row["course_id"],
            course_title=row["course_title"],
            kind=row["kind"],
            title=row["title"],
            original_name=row["original_name"],
            mime_type=row["mime_type"],
            status=row["status"],
            summary=row["summary"],
            content=row["content"],
            tags=json.loads(row["tags_json"]),
            knowledge_count=row["knowledge_count"],
            size_bytes=row["size_bytes"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _chunk_from_row(row: sqlite3.Row) -> KnowledgeChunk:
        return KnowledgeChunk(
            id=row["id"],
            asset_id=row["asset_id"],
            asset_title=row["asset_title"],
            course_id=row["course_id"],
            course_title=row["course_title"],
            title=row["title"],
            excerpt=row["excerpt"],
            tags=json.loads(row["tags_json"]),
        )

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
