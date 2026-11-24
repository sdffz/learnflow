from __future__ import annotations

from typing import Literal

from pydantic import Field

from .domain import utc_now
from .knowledge_domain import CamelModel

ConnectionStatus = Literal["pending", "connected", "expired", "error", "revoked"]
LoginStatus = Literal[
    "pending",
    "confirming",
    "connected",
    "cancelled",
    "expired",
    "verification_required",
]
JobStatus = Literal[
    "queued",
    "reading",
    "downloading",
    "parsing",
    "completed",
    "partial_failed",
    "cancelled",
    "session_expired",
]
JobItemStatus = Literal[
    "queued",
    "downloading",
    "parsing",
    "completed",
    "skipped",
    "failed",
]
JobItemKind = Literal["file", "video_links", "zip_file"]


class LearningConnection(CamelModel):
    id: str
    provider: Literal["chaoxing"] = "chaoxing"
    remote_nickname: str | None = None
    status: ConnectionStatus = "pending"
    expires_at: str | None = None
    last_synced_at: str | None = None
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class StoredConnection(LearningConnection):
    cookies: dict[str, str] | None = Field(default=None, exclude=True)
    account_fingerprint: str | None = Field(default=None, exclude=True)


class PreviewFile(CamelModel):
    id: str
    name: str
    extension: str
    size_bytes: int = 0
    supported: bool = True
    excluded_reason: str | None = None
    remote_url: str | None = Field(default=None, exclude=True)
    archive_member: str | None = Field(default=None, exclude=True)


class PreviewCourse(CamelModel):
    id: str
    title: str
    teacher: str = ""
    documents: list[PreviewFile] = Field(default_factory=list)
    video_links: list[str] = Field(default_factory=list)


class ImportPreview(CamelModel):
    id: str
    courses: list[PreviewCourse] = Field(default_factory=list)
    total_documents: int = 0
    total_video_links: int = 0
    total_bytes: int = 0
    generated_at: str = Field(default_factory=utc_now)
    expires_at: str
    archive_relpath: str | None = Field(default=None, exclude=True)


class ImportJobItem(CamelModel):
    id: str
    job_id: str
    kind: JobItemKind
    title: str
    external_course_id: str
    external_file_id: str | None = None
    target_course_id: str
    status: JobItemStatus = "queued"
    attempts: int = 0
    checksum: str | None = None
    asset_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    source_url: str | None = Field(default=None, exclude=True)
    archive_member: str | None = Field(default=None, exclude=True)
    size_bytes: int = 0
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class ImportJob(CamelModel):
    id: str
    preview_id: str
    status: JobStatus = "queued"
    progress: int = Field(default=0, ge=0, le=100)
    total_items: int = 0
    completed_items: int = 0
    failed_items: int = 0
    skipped_items: int = 0
    cancel_requested: bool = False
    created_at: str = Field(default_factory=utc_now)
    started_at: str | None = None
    finished_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class FolderMapping(CamelModel):
    preview_course_id: str
    mode: Literal["new", "merge", "skip"] = "new"
    target_course_id: str | None = None
    folder_title: str | None = None


class CreateImportRequest(CamelModel):
    preview_id: str
    mappings: list[FolderMapping] = Field(default_factory=list)


class LearningLogin(CamelModel):
    id: str
    status: LoginStatus = "pending"
    expires_at: str
    revision: int = 0
    message: str | None = None


class QrLoginTicket(CamelModel):
    id: str
    qr_png: bytes = Field(exclude=True)
    expires_at: str
    revision: int = 0


class FinishLogin(CamelModel):
    status: LoginStatus
    remote_nickname: str | None = None
    message: str | None = None


class LearningStatus(CamelModel):
    enabled: bool
    connection: LearningConnection | None = None


class JobDetail(CamelModel):
    job: ImportJob
    items: list[ImportJobItem] = Field(default_factory=list)

