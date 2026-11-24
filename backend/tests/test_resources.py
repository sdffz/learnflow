import pytest

from app.domain import LearnerProfile, ProfileDimension
from app.model_gateway import MockProvider
from app.resource_agents import RESOURCE_ROLES, ResourceBundle


def _profile():
    return LearnerProfile(
        dimensions={
            "编程基础": ProfileDimension(
                value="零基础", evidence="零基础", confidence=0.9
            ),
            "学习目标": ProfileDimension(
                value="完成项目", evidence="项目", confidence=0.9
            ),
            "资源偏好": ProfileDimension(
                value="视频动画", evidence="视频", confidence=0.9
            ),
            "当前薄弱点": ProfileDimension(
                value="神经网络", evidence="神经网络", confidence=0.9
            ),
            "认知风格": ProfileDimension(
                value="视觉型", evidence="图", confidence=0.9
            ),
            "学习节奏": ProfileDimension(
                value="每周6小时", evidence="每周6小时", confidence=0.9
            ),
        }
    )


class RecordingProvider:
    """Wraps a provider and records every role the bundle asks for."""

    def __init__(self, inner=None):
        self.inner = inner or MockProvider()
        self.calls: list[tuple[str, dict]] = []

    async def complete_json(self, task: str, payload: dict) -> dict:
        self.calls.append((task, payload))
        return await self.inner.complete_json(task, payload)


class ModelProvider(RecordingProvider):
    """Answers with the full per-role shape a real model is asked for."""

    async def complete_json(self, task: str, payload: dict) -> dict:
        self.calls.append((task, payload))
        topic = payload["topic"]
        if task == "document":
            return {
                "title": f"{topic}·模型讲解",
                "sections": [
                    {"heading": "针对你的薄弱点", "body": "模型为薄弱点专门写了这一节"},
                    {"heading": "核心概念", "body": f"模型为{topic}生成的核心观点"},
                ],
                "self_check": "模型生成的自检题",
            }
        if task == "mindmap":
            return {
                "root": topic,
                "branches": [
                    {"label": "模型分支一", "children": ["子节点A", "子节点B"]},
                    {"label": "模型分支二"},
                ],
            }
        if task == "quiz":
            return {
                "questions": [
                    {
                        "stem": "模型生成的题干？",
                        "options": ["正确项", "干扰项一", "干扰项二"],
                        "answer": 1,
                        "explanation": "模型生成的解析",
                    }
                ]
            }
        if task == "codelab":
            return {
                "title": f"{topic}·模型实验",
                "task": "模型生成的任务",
                "starter": "def todo():\n    pass\n",
                "solution": "print('model')",
                "expected_output": "model",
                "explanation": "模型生成的说明",
            }
        if task == "slides":
            return {
                "title": f"{topic}·模型课件",
                "slides": [
                    {"title": "模型页一", "kicker": "PAGE", "body": "模型正文一"},
                    {"title": "模型页二", "kicker": "PAGE", "body": "模型正文二"},
                ],
            }
        if task == "animation":
            return {
                "headline": "模型生成的主旨",
                "intro": "模型生成的开场",
                "steps": [
                    {"title": "模型步骤一", "caption": "第一步说明"},
                    {"title": "模型步骤二", "caption": "第二步说明"},
                ],
            }
        return {}


class BrokenProvider(RecordingProvider):
    async def complete_json(self, task: str, payload: dict) -> dict:
        self.calls.append((task, payload))
        raise RuntimeError("upstream 500")


@pytest.mark.asyncio
async def test_generates_all_six_resource_types():
    resources = await ResourceBundle().generate(_profile(), "神经网络", MockProvider())

    assert {resource.type for resource in resources} == set(RESOURCE_ROLES)
    assert all(resource.status == "verified" for resource in resources)


@pytest.mark.asyncio
async def test_each_role_is_a_separate_model_call():
    provider = RecordingProvider()

    await ResourceBundle().generate(_profile(), "神经网络", provider)

    roles = [task for task, _ in provider.calls]
    assert roles == list(RESOURCE_ROLES)
    # Every call must carry the personalization context of its own role.
    assert all(payload["topic"] == "神经网络" for _, payload in provider.calls)
    assert all(payload["profile"] for _, payload in provider.calls)


@pytest.mark.asyncio
async def test_model_output_overrides_the_fallback_template():
    resources = await ResourceBundle().generate(
        _profile(), "神经网络", ModelProvider()
    )

    document = next(item for item in resources if item.type == "document")
    assert "针对你的薄弱点" in document.content["markdown"]
    assert "模型为薄弱点专门写了这一节" in document.content["markdown"]
    assert document.metadata["generated_by"] == "model"

    mindmap = next(item for item in resources if item.type == "mindmap")
    labels = [child["label"] for child in mindmap.content["root"]["children"]]
    assert "模型分支一" in labels
    # Nested children are preserved rather than flattened away.
    first = mindmap.content["root"]["children"][0]
    assert [c["label"] for c in first["children"]] == ["子节点A", "子节点B"]

    quiz = next(item for item in resources if item.type == "quiz")
    question = quiz.content["questions"][0]
    assert question["answer"] == 1
    assert question["options"][1] == "干扰项一"


@pytest.mark.asyncio
async def test_out_of_range_answer_is_dropped():
    """A model that miscounts its own options must not produce a broken quiz."""

    class BadAnswer(ModelProvider):
        async def complete_json(self, task, payload):
            result = await super().complete_json(task, payload)
            if task == "quiz":
                result["questions"][0]["answer"] = 9
            return result

    resources = await ResourceBundle().generate(_profile(), "神经网络", BadAnswer())
    quiz = next(item for item in resources if item.type == "quiz")

    # The unusable question is rejected, so the role degrades to fallback.
    assert quiz.metadata["generated_by"] == "template"
    assert quiz.content["questions"][0]["answer"] == 0


@pytest.mark.asyncio
async def test_model_failure_degrades_to_template_without_losing_resources():
    resources = await ResourceBundle().generate(
        _profile(), "神经网络", BrokenProvider()
    )

    assert len(resources) == len(RESOURCE_ROLES)
    assert all(resource.status == "verified" for resource in resources)
    assert all(resource.metadata["generated_by"] == "template" for resource in resources)


@pytest.mark.asyncio
async def test_beginner_and_project_profiles_get_different_resources():
    beginner = _profile()
    project = beginner.model_copy(deep=True)
    project.dimensions["编程基础"].value = "熟练"

    beginner_resources = await ResourceBundle().generate(
        beginner, "神经网络", MockProvider()
    )
    project_resources = await ResourceBundle().generate(
        project, "神经网络", MockProvider()
    )
    beginner_code = next(
        item for item in beginner_resources if item.type == "codelab"
    )
    project_code = next(item for item in project_resources if item.type == "codelab")

    assert beginner_code.metadata["difficulty"] != project_code.metadata["difficulty"]


@pytest.mark.asyncio
async def test_animation_is_safe_html():
    animation = next(
        item
        for item in await ResourceBundle().generate(
            _profile(), "神经网络", MockProvider()
        )
        if item.type == "animation"
    )

    assert animation.content["html"].startswith("<!doctype html>")
    assert "<script src=" not in animation.content["html"]


@pytest.mark.asyncio
async def test_animation_duration_tracks_step_count():
    short = await ResourceBundle().generate(
        _profile(),
        "神经网络",
        ModelProvider(),
    )
    animation = next(item for item in short if item.type == "animation")

    # ModelProvider answers with two steps.
    assert animation.content["duration_seconds"] == 6 + 2 * 3
    assert "模型步骤一" in animation.content["html"]
    assert "第一步说明" in animation.content["html"]


@pytest.mark.asyncio
async def test_animation_escapes_model_supplied_html():
    class Injecting(ModelProvider):
        async def complete_json(self, task, payload):
            result = await super().complete_json(task, payload)
            if task == "animation":
                result["steps"][0]["title"] = "<script>alert(1)</script>"
                result["headline"] = "<img src=x onerror=alert(2)>"
            return result

    resources = await ResourceBundle().generate(_profile(), "神经网络", Injecting())
    html = next(item for item in resources if item.type == "animation").content["html"]

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "onerror=alert(2)" not in html


@pytest.mark.asyncio
async def test_personal_sources_are_passed_to_every_role():
    class _Chunk:
        asset_id = "asset-1"
        asset_title = "课堂板书"
        course_title = "人工智能导论"
        title = "反向传播"
        excerpt = "反向传播通过链式法则计算梯度。"

    provider = RecordingProvider()
    await ResourceBundle().generate(
        _profile(), "神经网络", provider, [_Chunk()]
    )

    for _, payload in provider.calls:
        assert payload["sources"][0]["assetTitle"] == "课堂板书"


@pytest.mark.asyncio
async def test_sources_never_overwrite_topic_content():
    """Retrieved excerpts must not replace the topic's own teaching material.

    Regression: substituting an excerpt into big_idea produced documents whose
    body talked about a different topic than the heading.
    """

    class OffTopicChunk:
        asset_id = "asset-2"
        asset_title = "人工智能导论"
        course_title = "人工智能导论"
        title = "人工智能的发展路线"
        excerpt = "人工智能的发展可以概括为符号主义、连接主义与行为主义等路线。"

    provider = MockProvider()
    resources = await ResourceBundle().generate(
        _profile(), "神经网络", provider, [OffTopicChunk()]
    )

    document = next(item for item in resources if item.type == "document")
    markdown = document.content["markdown"]
    # The topic's own definition survives instead of being replaced by the
    # unrelated excerpt, and the excerpt never leaks into the body.
    assert "神经网络通过多层可学习单元" in markdown
    assert "符号主义" not in markdown
    # The source is still credited in the citation block.
    assert "人工智能的发展路线" in markdown