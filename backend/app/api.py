import asyncio
import json
import re
from html import escape
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .assessment_agent import AssessmentAgent
from .auth import AuthContext, AuthManager
from .config import load_settings
from .domain import (
    AgentEvent,
    GenerationRun,
    Learner,
    LearnerProfile,
    ProfileUpdate,
)
from .knowledge import KnowledgeBase, TutorAnswer
from .knowledge_domain import KnowledgeChunk
from .knowledge_store import KnowledgeStore
from .learning_graph import LearningGraph
from .model_gateway import create_provider
from .path_agent import LearningPath, PathAgent
from .profile_agent import extract_profile_with_model
from .repository import Repository
from .resource_agents import LearningResource, ResourceBundle
from .safety import SafetyService
from .stream import RunStream


class CreateLearnerRequest(BaseModel):
    persona_id: str | None = None
    name: str | None = None


class ProfileChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    topic: str = Field(default="神经网络", min_length=1, max_length=100)
    course_id: str | None = Field(default=None, alias="courseId")


class TutorRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class AssessmentRequest(BaseModel):
    phase: str = "post"
    answers: dict[str, int]


def _load_personas(data_root: Path) -> list[dict]:
    payload = json.loads((data_root / "personas.json").read_text(encoding="utf-8"))
    return payload["personas"]


def _require_learner(
    repository: Repository,
    learner_id: str,
    workspace_id: str,
) -> Learner:
    learner = repository.get_learner(learner_id, workspace_id)
    if learner is None:
        raise HTTPException(status_code=404, detail="learner_not_found")
    return learner


def _download_payload(resource: LearningResource) -> tuple[str, str, str]:
    safe_title = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", resource.title).strip("-")
    if resource.type == "document":
        return (
            f"{safe_title}.md",
            "text/markdown; charset=utf-8",
            resource.content["markdown"],
        )
    if resource.type == "codelab":
        return (
            f"{safe_title}.py",
            "text/x-python; charset=utf-8",
            resource.content["solution"],
        )
    if resource.type == "animation":
        return (
            f"{safe_title}.html",
            "text/html; charset=utf-8",
            resource.content["html"],
        )
    if resource.type == "slides":
        slides = "".join(
            f"<section><small>{escape(slide['kicker'])}</small>"
            f"<h2>{escape(slide['title'])}</h2>"
            f"<p>{escape(slide['body'])}</p></section>"
            for slide in resource.content["slides"]
        )
        html = (
            "<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
            "<style>body{margin:0;font-family:system-ui;background:#f5f0e7;color:#15324a}"
            "section{min-height:100vh;display:grid;align-content:center;padding:8vw;"
            "border-bottom:1px solid #bbb}small{color:#e25d3f;font-weight:700}"
            "h2{font-size:clamp(34px,7vw,80px);margin:.2em 0}p{font-size:clamp(18px,3vw,30px)}"
            "</style>"
            f"{slides}</html>"
        )
        return f"{safe_title}.html", "text/html; charset=utf-8", html
    return (
        f"{safe_title}.json",
        "application/json; charset=utf-8",
        json.dumps(resource.content, ensure_ascii=False, indent=2),
    )


def build_router(
    *,
    repository: Repository,
    knowledge_base: KnowledgeBase,
    data_root: Path,
    auth_manager: AuthManager,
    knowledge_store: KnowledgeStore | None = None,
) -> APIRouter:
    router = APIRouter(
        prefix="/api",
        dependencies=[Depends(auth_manager.require_auth)],
    )
    personas = _load_personas(data_root)
    persona_index = {item["id"]: item for item in personas}
    splitter = RunStream(repository)
    safety = SafetyService()
    path_agent = PathAgent()
    assessment_agent = AssessmentAgent()
    provider = create_provider(load_settings())
    graph = LearningGraph(ResourceBundle(), provider)
    background_tasks: set[asyncio.Task] = set()

    async def execute_run(
        run: GenerationRun,
        profile: LearnerProfile,
        personal_sources: list[KnowledgeChunk],
        workspace_id: str,
    ) -> None:
        repository.update_run(
            run.id,
            status="running",
            progress=3,
            workspace_id=workspace_id,
        )
        try:
            async for event in graph.generate(
                run.id,
                profile,
                run.topic,
                personal_sources,
            ):
                repository.append_event(event)
                resource_payload = event.data.get("resource")
                if resource_payload:
                    repository.save_resource(
                        run.id,
                        LearningResource.model_validate(resource_payload),
                        workspace_id,
                    )
                progress = min(96, 3 + event.sequence * 8)
                repository.update_run(
                    run.id,
                    status="running",
                    progress=progress,
                    workspace_id=workspace_id,
                )
                await splitter.publish(event)

            final_event = repository.list_events(run.id)[-1]
            repository.update_run(
                run.id,
                status=final_event.status,
                progress=100 if final_event.status == "completed" else 92,
                workspace_id=workspace_id,
            )
        except Exception as exc:
            sequence = len(repository.list_events(run.id)) + 1
            failure = AgentEvent(
                sequence=sequence,
                run_id=run.id,
                agent="orchestrator",
                phase="run",
                status="failed",
                summary="资源生成失败，请稍后重试",
                data={"error": type(exc).__name__},
            )
            repository.append_event(failure)
            repository.update_run(
                run.id,
                status="failed",
                progress=0,
                error=str(exc),
                workspace_id=workspace_id,
            )
            await splitter.publish(failure)

    @router.get("/personas")
    def get_personas() -> dict:
        return {"personas": personas}

    @router.post("/learners", status_code=201)
    def create_learner(
        request: CreateLearnerRequest,
        http_request: Request,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> Learner:
        persona = persona_index.get(request.persona_id) if request.persona_id else None
        if request.persona_id and persona is None:
            raise HTTPException(status_code=404, detail="persona_not_found")
        learner = Learner(
            id=uuid4().hex,
            name=request.name or (persona["name"] if persona else "我的学习空间"),
            persona_id=request.persona_id,
            profile=(
                LearnerProfile.model_validate(persona["profile"])
                if persona
                else LearnerProfile()
            ),
        )
        created = repository.create_learner(learner, auth.workspace_id)
        auth_manager.audit(
            workspace_id=auth.workspace_id,
            user_id=auth.user_id,
            action="learner.create",
            resource_type="learner",
            resource_id=created.id,
            ip_address=http_request.client.host if http_request.client else None,
        )
        return created

    @router.get("/learners/{learner_id}/profile")
    def get_profile(
        learner_id: str,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> dict:
        learner = _require_learner(repository, learner_id, auth.workspace_id)
        return {
            "learner": learner.model_dump(mode="json"),
            "profile": learner.profile.model_dump(),
        }

    @router.post("/learners/{learner_id}/profile/chat")
    async def chat_profile(
        learner_id: str,
        request: ProfileChatRequest,
        http_request: Request,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> ProfileUpdate:
        learner = _require_learner(repository, learner_id, auth.workspace_id)
        result = safety.check(request.message)
        if not result.allowed:
            raise HTTPException(status_code=422, detail=result.reason)
        update, source = await extract_profile_with_model(
            learner.profile,
            request.message,
            provider,
        )
        repository.update_profile(
            learner_id,
            update.profile,
            auth.workspace_id,
        )
        auth_manager.audit(
            workspace_id=auth.workspace_id,
            user_id=auth.user_id,
            action="profile.update",
            resource_type="learner",
            resource_id=learner_id,
            metadata={"extractor": source},
            ip_address=http_request.client.host if http_request.client else None,
        )
        return update

    @router.post("/learners/{learner_id}/runs", status_code=202)
    async def create_run(
        learner_id: str,
        request: CreateRunRequest,
        http_request: Request,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> GenerationRun:
        learner = _require_learner(repository, learner_id, auth.workspace_id)
        personal_sources: list[KnowledgeChunk] = []
        if request.course_id:
            if (
                knowledge_store is None
                or knowledge_store.get_course(
                    request.course_id,
                    auth.workspace_id,
                )
                is None
            ):
                raise HTTPException(status_code=404, detail="course_not_found")
            personal_sources = knowledge_store.search(
                request.topic,
                course_id=request.course_id,
                workspace_id=auth.workspace_id,
            ).items
            if not personal_sources:
                personal_sources = knowledge_store.search(
                    "",
                    course_id=request.course_id,
                    workspace_id=auth.workspace_id,
                ).items[:6]
        run = GenerationRun(
            id=uuid4().hex,
            learner_id=learner_id,
            topic=request.topic,
        )
        repository.create_run(run, auth.workspace_id)
        auth_manager.audit(
            workspace_id=auth.workspace_id,
            user_id=auth.user_id,
            action="run.create",
            resource_type="run",
            resource_id=run.id,
            metadata={
                "topic": request.topic,
                "course_id": request.course_id,
            },
            ip_address=http_request.client.host if http_request.client else None,
        )
        task = asyncio.create_task(
            execute_run(
                run,
                learner.profile,
                personal_sources,
                auth.workspace_id,
            )
        )
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
        return run

    @router.get("/runs/{run_id}")
    def get_run(
        run_id: str,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> dict:
        run = repository.get_run(run_id, auth.workspace_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run_not_found")
        return {
            **run.model_dump(mode="json"),
            "events": [
                event.model_dump(mode="json")
                for event in repository.list_events(run_id)
            ],
            "resources": [
                resource.model_dump(mode="json")
                for resource in repository.list_resources(
                    run_id,
                    auth.workspace_id,
                )
            ],
        }

    @router.get("/runs/{run_id}/stream")
    async def stream_run(
        run_id: str,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> StreamingResponse:
        if repository.get_run(run_id, auth.workspace_id) is None:
            raise HTTPException(status_code=404, detail="run_not_found")

        async def frames():
            async for event in splitter.stream(run_id, auth.workspace_id):
                payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
                yield f"event: agent\ndata: {payload}\n\n"

        return StreamingResponse(
            frames(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/resources/{resource_id}")
    def get_resource(
        resource_id: str,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> LearningResource:
        resource = repository.get_resource(resource_id, auth.workspace_id)
        if resource is None:
            raise HTTPException(status_code=404, detail="resource_not_found")
        return resource

    @router.get("/resources/{resource_id}/download")
    def download_resource(
        resource_id: str,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> Response:
        resource = repository.get_resource(resource_id, auth.workspace_id)
        if resource is None:
            raise HTTPException(status_code=404, detail="resource_not_found")
        filename, media_type, content = _download_payload(resource)
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
            },
        )

    @router.post("/learners/{learner_id}/paths")
    def create_learning_path(
        learner_id: str,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> LearningPath:
        learner = _require_learner(repository, learner_id, auth.workspace_id)
        return path_agent.build(learner)

    @router.post("/learners/{learner_id}/tutor")
    def tutor(
        learner_id: str,
        request: TutorRequest,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ) -> TutorAnswer:
        _require_learner(repository, learner_id, auth.workspace_id)
        result = safety.check(request.question)
        if not result.allowed:
            return TutorAnswer(
                text="这个问题涉及不安全内容，系统不能提供相关帮助。",
                refused=True,
                refusal_reason=result.reason,
            )
        return knowledge_base.answer(request.question)

    @router.get("/assessments/questions")
    def assessment_questions() -> dict:
        return {"questions": assessment_agent.public_questions()}

    @router.post("/learners/{learner_id}/assessments")
    def submit_assessment(
        learner_id: str,
        request: AssessmentRequest,
        http_request: Request,
        auth: AuthContext = Depends(auth_manager.require_auth),
    ):
        learner = _require_learner(repository, learner_id, auth.workspace_id)
        try:
            result = assessment_agent.grade(learner.profile, request.answers)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        repository.update_profile(
            learner_id,
            result.updated_profile,
            auth.workspace_id,
        )
        auth_manager.audit(
            workspace_id=auth.workspace_id,
            user_id=auth.user_id,
            action="assessment.submit",
            resource_type="learner",
            resource_id=learner_id,
            metadata={"score": result.score},
            ip_address=http_request.client.host if http_request.client else None,
        )
        return result

    return router
