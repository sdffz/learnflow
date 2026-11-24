from datetime import UTC, datetime

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class ProfileDimension(BaseModel):
    value: str
    evidence: str
    confidence: float = Field(ge=0, le=1)
    updated_at: str = Field(default_factory=utc_now)


class LearnerProfile(BaseModel):
    dimensions: dict[str, ProfileDimension] = Field(default_factory=dict)
    mastery: dict[str, float] = Field(default_factory=dict)


class ProfileUpdate(BaseModel):
    profile: LearnerProfile
    assistant_message: str
    changed_dimensions: list[str] = Field(default_factory=list)


class Learner(BaseModel):
    id: str
    name: str
    course_id: str = "ai-intro"
    persona_id: str | None = None
    profile: LearnerProfile = Field(default_factory=LearnerProfile)
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class GenerationRun(BaseModel):
    id: str
    learner_id: str
    topic: str
    status: str = "queued"
    progress: int = Field(default=0, ge=0, le=100)
    error: str | None = None
    created_at: str = Field(default_factory=utc_now)
    completed_at: str | None = None


class AgentEvent(BaseModel):
    sequence: int
    run_id: str
    agent: str
    phase: str
    status: str
    summary: str
    data: dict = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)
