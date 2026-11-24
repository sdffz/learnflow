from collections.abc import AsyncIterator

from .domain import AgentEvent, LearnerProfile
from .knowledge_domain import KnowledgeChunk
from .model_gateway import ModelProvider
from .resource_agents import ResourceBundle


class LearningGraph:
    def __init__(self, bundle: ResourceBundle, provider: ModelProvider):
        self.bundle = bundle
        self.provider = provider

    async def generate(
        self,
        run_id: str,
        profile: LearnerProfile,
        topic: str,
        personal_sources: list[KnowledgeChunk] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        sequence = 0
        sources = personal_sources or []

        def event(
            agent: str,
            phase: str,
            status: str,
            summary: str,
            data: dict | None = None,
        ) -> AgentEvent:
            nonlocal sequence
            sequence += 1
            return AgentEvent(
                sequence=sequence,
                run_id=run_id,
                agent=agent,
                phase=phase,
                status=status,
                summary=summary,
                data=data or {},
            )

        yield event(
            "orchestrator",
            "run",
            "running",
            "正在读取画像并拆分学习任务",
        )
        yield event(
            "curriculum",
            "plan",
            "completed",
            (
                f"已读取 {len(sources)} 个个人知识片段并定位知识依赖"
                if sources
                else "已定位课程目标与知识依赖"
            ),
            {"sources": [source.model_dump(mode="json") for source in sources]},
        )
        yield event("resource_planner", "plan", "completed", "已确定六类资源组合")

        resources = await self.bundle.generate(
            profile,
            topic,
            self.provider,
            sources,
        )
        completed = 0
        for resource in resources:
            yield event(
                resource.type,
                "resource",
                "running",
                f"正在生成{resource.title}",
            )
            if resource.status == "failed":
                yield event(
                    resource.type,
                    "resource",
                    "failed",
                    f"{resource.title}生成失败",
                )
                continue
            completed += 1
            yield event(
                resource.type,
                "resource",
                "completed",
                f"{resource.title}已通过质检",
                {"resource": resource.model_dump()},
            )

        yield event(
            "review",
            "review",
            "completed",
            f"已完成 {completed} 个资源的质量与安全复核",
        )
        final_status = "completed" if completed == len(resources) else "partial"
        summary = (
            "个性化资源包已生成"
            if final_status == "completed"
            else "资源包部分完成，可查看已成功内容"
        )
        yield event("orchestrator", "run", final_status, summary)
