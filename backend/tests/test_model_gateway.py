import json

import httpx
import pytest

from app.config import Settings
from app.domain import LearnerProfile
from app.model_gateway import MockProvider, OpenAICompatibleProvider, create_provider
from app.profile_agent import extract_profile_with_model
from app.resource_agents import RESOURCE_ROLES, ResourceBundle


@pytest.mark.asyncio
async def test_openai_compatible_provider_parses_json_content():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "```json\n{\"summary\": \"已生成\", \"score\": 0.9}\n```"
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://model.test/v1"
    ) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://model.test/v1",
            api_key="secret",
            model="test-model",
            client=client,
        )
        result = await provider.complete_json(
            "profile", {"message": "我零基础"}
        )

    assert result == {"summary": "已生成", "score": 0.9}
    assert requests[0].headers["authorization"] == "Bearer secret"
    body = json.loads(requests[0].content)
    assert body["response_format"] == {"type": "json_object"}
    assert body["model"] == "test-model"


@pytest.mark.asyncio
async def test_provider_sends_role_and_schema_hint_in_system_prompt():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "{}"}}]}
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://model.test/v1"
    ) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://model.test/v1/",
            api_key="k",
            model="m",
            client=client,
        )
        await provider.complete_json(
            "mindmap",
            {"topic": "神经网络", "output_schema": {"required": ["chain"]}},
        )

    body = json.loads(captured[0].content)
    system = body["messages"][0]["content"]
    assert "mindmap" in system
    assert "chain" in system
    # base_url is normalised so the endpoint never doubles the slash.
    assert str(captured[0].url).endswith("/v1/chat/completions")


@pytest.mark.asyncio
async def test_live_provider_drives_all_six_roles_end_to_end():
    """A stubbed live endpoint must reach every resource role."""
    seen_roles: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        user = json.loads(body["messages"][1]["content"])
        role = user["task"]
        seen_roles.append(role)
        answers = {
            "document": {
                "title": "模型标题",
                "sections": [{"heading": "模型小节", "body": f"{role} 的正文"}],
                "self_check": "模型自检",
            },
            "mindmap": {"root": "模型根", "branches": [{"label": "模型分支"}]},
            "quiz": {
                "questions": [
                    {"stem": "模型题干", "options": ["A", "B"], "answer": 1, "explanation": "解析"}
                ]
            },
            "codelab": {
                "title": "模型实验",
                "task": "模型任务",
                "starter": "pass",
                "solution": "print('ok')",
                "expected_output": "ok",
                "explanation": "说明",
            },
            "slides": {"title": "模型课件", "slides": [{"title": "页", "kicker": "K", "body": "正文"}]},
            "animation": {
                "headline": "模型主旨",
                "intro": "模型开场",
                "steps": [{"title": "步骤", "caption": "说明"}],
            },
        }
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(answers[role], ensure_ascii=False)
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://model.test/v1"
    ) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://model.test/v1",
            api_key="k",
            model="m",
            client=client,
        )
        resources = await ResourceBundle().generate(
            LearnerProfile(), "神经网络", provider
        )

    assert sorted(seen_roles) == sorted(RESOURCE_ROLES)
    assert all(item.metadata["generated_by"] == "model" for item in resources)
    document = next(item for item in resources if item.type == "document")
    assert "模型小节" in document.content["markdown"]


@pytest.mark.asyncio
async def test_each_role_prompt_carries_the_learner_profile():
    """Personalisation must reach the model, not just the UI label."""
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        payload = json.loads(body["messages"][1]["content"])["payload"]
        captured.append({"system": body["messages"][0]["content"], "payload": payload})
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "{}"}}]}
        )

    from app.domain import ProfileDimension

    profile = LearnerProfile(
        dimensions={
            "编程基础": ProfileDimension(value="零基础", evidence="x", confidence=0.9),
            "学习节奏": ProfileDimension(value="每周2小时", evidence="x", confidence=0.9),
            "当前薄弱点": ProfileDimension(value="操作系统", evidence="x", confidence=0.9),
        }
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://model.test/v1"
    ) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://model.test/v1", api_key="k", model="m", client=client
        )
        await ResourceBundle().generate(profile, "神经网络", provider)

    assert captured
    for call in captured:
        assert call["payload"]["profile"]["编程基础"] == "零基础"
        assert call["payload"]["profile"]["当前薄弱点"] == "操作系统"
        assert call["payload"]["difficulty"] == "入门"
        # The role instruction tells the model what to do with that profile.
        assert "payload.profile" in call["system"]


@pytest.mark.asyncio
async def test_live_profile_extraction_uses_model_dimensions():
    def handler(request: httpx.Request) -> httpx.Response:
        answer = {
            "dimensions": [
                {
                    "name": "认知风格",
                    "value": "结构优先",
                    "evidence": "喜欢先看大纲",
                    "confidence": 0.92,
                },
                {
                    "name": "兴趣方向",
                    "value": "多模态生成",
                    "evidence": "想做视频课件",
                    "confidence": 0.8,
                },
                {
                    "name": "不存在的维度",
                    "value": "应被丢弃",
                    "evidence": "x",
                    "confidence": 0.9,
                },
            ]
        }
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(answer, ensure_ascii=False)}}
                ]
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://model.test/v1"
    ) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://model.test/v1",
            api_key="k",
            model="m",
            client=client,
        )
        update, source = await extract_profile_with_model(
            LearnerProfile(), "我喜欢先看大纲，想做视频课件", provider
        )

    assert source == "model"
    assert update.profile.dimensions["认知风格"].value == "结构优先"
    assert update.profile.dimensions["兴趣方向"].value == "多模态生成"
    # Unknown dimension names are rejected rather than stored.
    assert "不存在的维度" not in update.profile.dimensions


@pytest.mark.asyncio
async def test_profile_falls_back_to_rules_when_model_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://model.test/v1"
    ) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://model.test/v1",
            api_key="k",
            model="m",
            client=client,
        )
        update, source = await extract_profile_with_model(
            LearnerProfile(), "我零基础", provider
        )

    assert source == "rules"
    assert update.profile.dimensions["编程基础"].value == "零基础"


def test_create_provider_uses_mock_without_key():
    provider = create_provider(
        Settings(
            model_mode="mock",
            model_api_key=None,
            model_base_url=None,
            model_name=None,
        )
    )

    assert isinstance(provider, MockProvider)


def test_create_provider_uses_live_adapter_with_key():
    provider = create_provider(
        Settings(
            model_mode="live",
            model_api_key="k",
            model_base_url="https://spark-api-open.xf-yun.com/v1",
            model_name="generalv3.5",
        )
    )

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.model == "generalv3.5"