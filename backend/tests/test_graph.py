import pytest

from app.domain import LearnerProfile, ProfileDimension
from app.learning_graph import LearningGraph
from app.model_gateway import MockProvider
from app.resource_agents import ResourceBundle


@pytest.mark.asyncio
async def test_graph_emits_progress_for_all_agents():
    profile = LearnerProfile(
        dimensions={
            "编程基础": ProfileDimension(
                value="入门", evidence="会一点", confidence=0.8
            ),
            "资源偏好": ProfileDimension(
                value="图解", evidence="图", confidence=0.8
            ),
        }
    )
    graph = LearningGraph(ResourceBundle(), MockProvider())

    events = [
        event async for event in graph.generate("run-1", profile, "神经网络")
    ]

    assert events[0].agent == "orchestrator"
    assert events[-1].status == "completed"
    assert {
        "document",
        "mindmap",
        "quiz",
        "codelab",
        "slides",
        "animation",
    }.issubset({event.agent for event in events})


@pytest.mark.asyncio
async def test_failed_resource_does_not_abort_remaining_resources():
    class FlakyBundle(ResourceBundle):
        async def generate(self, profile, topic, provider, personal_sources=None):
            resources = await super().generate(
                profile,
                topic,
                provider,
                personal_sources,
            )
            resources[0].status = "failed"
            return resources

    graph = LearningGraph(FlakyBundle(), MockProvider())

    events = [
        event async for event in graph.generate("run-2", LearnerProfile(), "搜索")
    ]

    assert any(event.status == "failed" for event in events)
    assert sum(event.status == "completed" for event in events) >= 5
    assert events[-1].phase == "run"


@pytest.mark.asyncio
async def test_graph_records_which_roles_used_the_model():
    from app.resource_agents import RESOURCE_ROLES

    class CountingProvider:
        def __init__(self):
            self.calls = 0

        async def complete_json(self, task, payload):
            self.calls += 1
            return {}

    provider = CountingProvider()
    graph = LearningGraph(ResourceBundle(), provider)

    [event async for event in graph.generate("run-3", LearnerProfile(), "神经网络")]

    assert provider.calls == len(RESOURCE_ROLES)
