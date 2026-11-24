from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from .domain import utc_now


def normalize_tags(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        tag = value.strip()
        key = tag.casefold()
        if tag and key not in seen:
            seen.add(key)
            result.append(tag)
    return result[:12]


def excerpt(text: str, limit: int = 180) -> str:
    compact = " ".join(text.split())
    return compact[:limit]


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class CourseCreate(CamelModel):
    title: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    color: str = Field(default="#e25d3f", pattern=r"^#[0-9a-fA-F]{6}$")

    @field_validator("title", "description", mode="before")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class CourseUpdate(CamelModel):
    title: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    color: str | None = Field(
        default=None,
        pattern=r"^#[0-9a-fA-F]{6}$",
    )

    @field_validator("title", "description", mode="before")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value


class NoteCreate(CamelModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=100_000)
    tags: list[str] = Field(default_factory=list)

    @field_validator("title", "content", mode="before")
    @classmethod
    def strip_note_text(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value

    @field_validator("tags")
    @classmethod
    def normalize_note_tags(cls, value: list[str]) -> list[str]:
        return normalize_tags(value)


class Course(CamelModel):
    id: str
    title: str
    description: str = ""
    color: str = "#e25d3f"
    asset_count: int = 0
    knowledge_count: int = 0
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class KnowledgeChunk(CamelModel):
    id: str
    asset_id: str
    asset_title: str
    course_id: str
    course_title: str
    title: str
    excerpt: str
    tags: list[str] = Field(default_factory=list)


class KnowledgeAsset(CamelModel):
    id: str
    course_id: str
    course_title: str
    kind: Literal["file", "image", "note"]
    title: str
    original_name: str | None = None
    mime_type: str | None = None
    status: Literal["processing", "ready", "ready_image_only", "failed"]
    summary: str = ""
    content: str = ""
    tags: list[str] = Field(default_factory=list)
    knowledge_count: int = 0
    size_bytes: int = 0
    error: str | None = None
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class AssetDetail(KnowledgeAsset):
    chunks: list[KnowledgeChunk] = Field(default_factory=list)
    file_available: bool = False


class KnowledgeOverview(CamelModel):
    course_count: int
    asset_count: int
    knowledge_count: int
    pending_count: int
    recent_assets: list[KnowledgeAsset] = Field(default_factory=list)
    courses: list[Course] = Field(default_factory=list)
    top_tags: list[str] = Field(default_factory=list)


class KnowledgeSearchResponse(CamelModel):
    items: list[KnowledgeChunk] = Field(default_factory=list)
    total: int = 0
