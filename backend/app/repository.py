from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock
from uuid import uuid4

from .domain import AgentEvent, GenerationRun, Learner, LearnerProfile, utc_now
from .resource_agents import LearningResource
from .tenancy import DEFAULT_WORKSPACE_ID


class Repository:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = RLock()
        self._connection: sqlite3.Connection | None = None

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._connection:
            self._connection.executescript(
                """
                PRAGMA foreign_keys = ON;
                PRAGMA journal_mode = WAL;
                PRAGMA synchronous = NORMAL;
                PRAGMA busy_timeout = 5000;

                CREATE TABLE IF NOT EXISTS learners (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    course_id TEXT NOT NULL,
                    persona_id TEXT,
                    profile_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    learner_id TEXT NOT NULL REFERENCES learners(id),
                    topic TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS agent_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    sequence INTEGER NOT NULL,
                    agent TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, sequence)
                );

                CREATE TABLE IF NOT EXISTS resources (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    knowledge_point TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(
                "learners",
                "workspace_id",
                "TEXT NOT NULL DEFAULT 'default'",
            )
            self._ensure_column(
                "runs",
                "workspace_id",
                "TEXT NOT NULL DEFAULT 'default'",
            )
            self._ensure_column(
                "resources",
                "workspace_id",
                "TEXT NOT NULL DEFAULT 'default'",
            )
            self.connection.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_learners_workspace
                    ON learners(workspace_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_runs_workspace
                    ON runs(workspace_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_resources_workspace
                    ON resources(workspace_id, created_at);
                """
            )

    def _ensure_column(
        self,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {
            row["name"]
            for row in self.connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            self.connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("Repository is not initialized")
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def create_learner(
        self,
        learner: Learner,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> Learner:
        with self._lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO learners
                    (id, workspace_id, name, course_id, persona_id,
                     profile_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    learner.id,
                    workspace_id,
                    learner.name,
                    learner.course_id,
                    learner.persona_id,
                    learner.profile.model_dump_json(),
                    learner.created_at,
                    learner.updated_at,
                ),
            )
        return learner

    def get_learner(
        self,
        learner_id: str,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> Learner | None:
        with self._lock:
            row = self.connection.execute(
                """
                SELECT * FROM learners
                WHERE id = ? AND workspace_id = ?
                """,
                (learner_id, workspace_id),
            ).fetchone()
        if row is None:
            return None
        return Learner(
            id=row["id"],
            name=row["name"],
            course_id=row["course_id"],
            persona_id=row["persona_id"],
            profile=LearnerProfile.model_validate_json(row["profile_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def update_profile(
        self,
        learner_id: str,
        profile: LearnerProfile,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> None:
        with self._lock, self.connection:
            result = self.connection.execute(
                """
                UPDATE learners SET profile_json = ?, updated_at = ?
                WHERE id = ? AND workspace_id = ?
                """,
                (
                    profile.model_dump_json(),
                    utc_now(),
                    learner_id,
                    workspace_id,
                ),
            )
        if result.rowcount == 0:
            raise KeyError(learner_id)

    def create_run(
        self,
        run: GenerationRun,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> GenerationRun:
        with self._lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO runs
                    (id, workspace_id, learner_id, topic, status, progress,
                     error, created_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    workspace_id,
                    run.learner_id,
                    run.topic,
                    run.status,
                    run.progress,
                    run.error,
                    run.created_at,
                    run.completed_at,
                ),
            )
        return run

    def get_run(
        self,
        run_id: str,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> GenerationRun | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT * FROM runs WHERE id = ? AND workspace_id = ?",
                (run_id, workspace_id),
            ).fetchone()
        return self._run_from_row(row) if row else None

    def update_run(
        self,
        run_id: str,
        *,
        status: str,
        progress: int,
        error: str | None = None,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> None:
        completed_at = (
            utc_now() if status in {"completed", "partial", "failed"} else None
        )
        with self._lock, self.connection:
            result = self.connection.execute(
                """
                UPDATE runs
                SET status = ?, progress = ?, error = ?, completed_at = COALESCE(?, completed_at)
                WHERE id = ? AND workspace_id = ?
                """,
                (
                    status,
                    progress,
                    error,
                    completed_at,
                    run_id,
                    workspace_id,
                ),
            )
        if result.rowcount == 0:
            raise KeyError(run_id)

    def append_event(self, event: AgentEvent) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO agent_events
                    (run_id, sequence, agent, phase, status, summary, data_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.run_id,
                    event.sequence,
                    event.agent,
                    event.phase,
                    event.status,
                    event.summary,
                    json.dumps(event.data, ensure_ascii=False),
                    event.created_at,
                ),
            )

    def list_events(self, run_id: str) -> list[AgentEvent]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM agent_events WHERE run_id = ? ORDER BY sequence",
                (run_id,),
            ).fetchall()
        return [
            AgentEvent(
                sequence=row["sequence"],
                run_id=row["run_id"],
                agent=row["agent"],
                phase=row["phase"],
                status=row["status"],
                summary=row["summary"],
                data=json.loads(row["data_json"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def save_resource(
        self,
        run_id: str,
        resource: LearningResource,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> LearningResource:
        if resource.id is None:
            resource = resource.model_copy(update={"id": uuid4().hex})
        with self._lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO resources
                    (id, workspace_id, run_id, type, title, knowledge_point,
                     content_json, metadata_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resource.id,
                    workspace_id,
                    run_id,
                    resource.type,
                    resource.title,
                    resource.knowledge_point,
                    json.dumps(resource.content, ensure_ascii=False),
                    json.dumps(resource.metadata, ensure_ascii=False),
                    resource.status,
                    resource.created_at,
                ),
            )
        return resource

    def list_resources(
        self,
        run_id: str,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> list[LearningResource]:
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT * FROM resources
                WHERE run_id = ? AND workspace_id = ?
                ORDER BY rowid
                """,
                (run_id, workspace_id),
            ).fetchall()
        return [self._resource_from_row(row) for row in rows]

    def get_resource(
        self,
        resource_id: str,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> LearningResource | None:
        with self._lock:
            row = self.connection.execute(
                """
                SELECT * FROM resources
                WHERE id = ? AND workspace_id = ?
                """,
                (resource_id, workspace_id),
            ).fetchone()
        return self._resource_from_row(row) if row else None

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> GenerationRun:
        return GenerationRun(
            id=row["id"],
            learner_id=row["learner_id"],
            topic=row["topic"],
            status=row["status"],
            progress=row["progress"],
            error=row["error"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _resource_from_row(row: sqlite3.Row) -> LearningResource:
        return LearningResource(
            id=row["id"],
            type=row["type"],
            title=row["title"],
            knowledge_point=row["knowledge_point"],
            content=json.loads(row["content_json"]),
            metadata=json.loads(row["metadata_json"]),
            status=row["status"],
            created_at=row["created_at"],
        )
