import asyncio

import httpx
import pytest

from app.main import create_app


async def _client_for(tmp_path):
    app = create_app(data_dir=tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as registration_client:
        registration = await registration_client.post(
            "/api/auth/register",
            json={
                "name": "API 测试用户",
                "email": f"{tmp_path.name}@example.com",
                "password": "EnterprisePass123!",
            },
        )
    assert registration.status_code == 201
    cookie = registration.headers["set-cookie"].split(";", 1)[0]
    return httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Cookie": cookie},
    )


async def _wait_for_run(client, run_id):
    for _ in range(80):
        response = await client.get(f"/api/runs/{run_id}")
        payload = response.json()
        if payload["status"] in {"completed", "partial", "failed"}:
            return payload
        await asyncio.sleep(0.025)
    raise AssertionError(f"run {run_id} did not finish")


@pytest.mark.asyncio
async def test_learner_journey_reaches_generated_resources(tmp_path):
    async with await _client_for(tmp_path) as client:
        personas = (await client.get("/api/personas")).json()
        assert len(personas["personas"]) == 3

        learner_response = await client.post(
            "/api/learners", json={"persona_id": "beginner"}
        )
        assert learner_response.status_code == 201
        learner_id = learner_response.json()["id"]

        profile_response = await client.post(
            f"/api/learners/{learner_id}/profile/chat",
            json={
                "message": "我零基础，刚接触 AI，想完成项目，喜欢视频，每周学6小时。"
            },
        )
        profile = profile_response.json()
        assert profile_response.status_code == 200
        assert len(profile["profile"]["dimensions"]) >= 6

        run_response = await client.post(
            f"/api/learners/{learner_id}/runs", json={"topic": "神经网络"}
        )
        assert run_response.status_code == 202
        run_id = run_response.json()["id"]
        snapshot = await _wait_for_run(client, run_id)
        assert snapshot["status"] == "completed"
        assert len(snapshot["resources"]) == 6
        assert len(snapshot["events"]) >= 9

        resource_id = snapshot["resources"][0]["id"]
        download = await client.get(f"/api/resources/{resource_id}/download")
        assert download.status_code == 200
        assert "attachment" in download.headers["content-disposition"]

        stream = await client.get(f"/api/runs/{run_id}/stream")
        assert stream.status_code == 200
        assert "event: agent" in stream.text


@pytest.mark.asyncio
async def test_path_tutor_and_assessment_complete_the_learning_loop(tmp_path):
    async with await _client_for(tmp_path) as client:
        learner = (
            await client.post("/api/learners", json={"persona_id": "exam"})
        ).json()
        learner_id = learner["id"]

        path_response = await client.post(f"/api/learners/{learner_id}/paths")
        path = path_response.json()
        assert path_response.status_code == 200
        assert len(path["nodes"]) >= 5
        assert path["nodes"][0]["status"] == "current"

        tutor_response = await client.post(
            f"/api/learners/{learner_id}/tutor",
            json={"question": "什么是监督学习？"},
        )
        tutor = tutor_response.json()
        assert tutor_response.status_code == 200
        assert tutor["refused"] is False
        assert tutor["sources"]

        questions_response = await client.get("/api/assessments/questions")
        questions = questions_response.json()["questions"]
        assert questions_response.status_code == 200
        assert len(questions) == 5
        assert all("answer" not in item for item in questions)
        answers = {"q1": 0, "q2": 2, "q3": 0, "q4": 1, "q5": 1}
        assessment_response = await client.post(
            f"/api/learners/{learner_id}/assessments",
            json={"phase": "post", "answers": answers},
        )
        assessment = assessment_response.json()
        assert assessment_response.status_code == 200
        assert assessment["score"] == 100
        assert assessment["updated_profile"]["mastery"]
        assert assessment["recommendation"]


@pytest.mark.asyncio
async def test_unknown_learner_returns_404(tmp_path):
    async with await _client_for(tmp_path) as client:
        response = await client.get("/api/learners/missing/profile")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_personal_learner_can_start_without_demo_persona(tmp_path):
    async with await _client_for(tmp_path) as client:
        response = await client.post(
            "/api/learners",
            json={"name": "我的学习空间"},
        )

    assert response.status_code == 201
    learner = response.json()
    assert learner["name"] == "我的学习空间"
    assert learner["persona_id"] is None
    assert learner["profile"]["dimensions"] == {}


@pytest.mark.asyncio
async def test_run_uses_selected_personal_course_sources(tmp_path):
    async with await _client_for(tmp_path) as client:
        course = (await client.get("/api/courses")).json()["items"][0]
        source = await client.post(
            f"/api/courses/{course['id']}/notes",
            json={
                "title": "个人监督学习笔记",
                "content": "监督学习使用带标签数据训练分类器，并在验证集上评估泛化。",
                "tags": ["监督学习"],
            },
        )
        assert source.status_code == 201
        learner = (
            await client.post("/api/learners", json={"name": "我的学习空间"})
        ).json()
        run = (
            await client.post(
                f"/api/learners/{learner['id']}/runs",
                json={
                    "topic": "监督学习",
                    "courseId": course["id"],
                },
            )
        ).json()
        snapshot = await _wait_for_run(client, run["id"])

    assert snapshot["status"] == "completed"
    document = next(
        item for item in snapshot["resources"] if item["type"] == "document"
    )
    sources = document["metadata"]["sources"]
    assert sources[0]["assetTitle"] == "个人监督学习笔记"
    assert "个人监督学习笔记" in document["content"]["markdown"]
    assert "来自你的资料" in document["content"]["markdown"]


@pytest.mark.asyncio
async def test_downloaded_slides_escape_user_topic_html(tmp_path):
    async with await _client_for(tmp_path) as client:
        learner = (
            await client.post("/api/learners", json={"persona_id": "beginner"})
        ).json()
        run = (
            await client.post(
                f"/api/learners/{learner['id']}/runs",
                json={"topic": "<img src=x onerror=alert(1)>"},
            )
        ).json()
        snapshot = await _wait_for_run(client, run["id"])
        slides = next(
            resource
            for resource in snapshot["resources"]
            if resource["type"] == "slides"
        )

        response = await client.get(f"/api/resources/{slides['id']}/download")

    assert response.status_code == 200
    assert "<img src=x" not in response.text
    assert "&lt;img src=x" in response.text
