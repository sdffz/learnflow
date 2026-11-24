import sqlite3

import httpx
import pytest

from app.main import create_app


async def _client_for(app, base_url="http://test"):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(
        transport=transport,
        base_url=base_url,
        follow_redirects=True,
    )


async def _register(client, email: str, name: str = "测试用户"):
    return await client.post(
        "/api/auth/register",
        json={
            "name": name,
            "email": email,
            "password": "EnterprisePass123!",
        },
    )


@pytest.mark.asyncio
async def test_anonymous_requests_are_rejected(tmp_path):
    app = create_app(data_dir=tmp_path)
    async with await _client_for(app) as client:
        response = await client.get("/api/courses")

    assert response.status_code == 401
    assert response.json()["detail"] == "authentication_required"


@pytest.mark.asyncio
async def test_registration_sets_secure_session_and_me_returns_identity(tmp_path):
    app = create_app(data_dir=tmp_path)
    async with await _client_for(app, "https://test") as client:
        response = await _register(client, "Owner@Example.com")

        assert response.status_code == 201
        payload = response.json()
        assert payload["user"]["email"] == "owner@example.com"
        assert payload["workspace"]["role"] == "owner"
        assert payload["workspace"]["id"] == "default"

        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "samesite=lax" in cookie
        assert "secure" in cookie

        me = await client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["user"]["email"] == "owner@example.com"

    with sqlite3.connect(tmp_path / "learnflow.sqlite3") as connection:
        stored = connection.execute(
            "SELECT password_hash FROM users WHERE email = ?",
            ("owner@example.com",),
        ).fetchone()[0]
    assert "EnterprisePass123!" not in stored
    assert stored.startswith("scrypt$")


@pytest.mark.asyncio
async def test_second_user_cannot_read_or_update_first_users_data(tmp_path):
    app = create_app(data_dir=tmp_path)
    async with await _client_for(app) as first, await _client_for(app) as second:
        await _register(first, "first@example.com", "第一位用户")
        created = await first.post(
            "/api/courses",
            json={"title": "第一位用户的资料"},
        )
        assert created.status_code == 201
        course_id = created.json()["id"]
        note = await first.post(
            f"/api/courses/{course_id}/notes",
            json={
                "title": "私有笔记",
                "content": "只有第一位用户能够读取这条笔记。",
                "tags": ["私有"],
            },
        )
        assert note.status_code == 201
        asset_id = note.json()["id"]

        await _register(second, "second@example.com", "第二位用户")
        second_courses = await second.get("/api/courses")
        titles = [item["title"] for item in second_courses.json()["items"]]
        assert "第一位用户的资料" not in titles

        cross_course = await second.get(f"/api/courses/{course_id}")
        cross_update = await second.patch(
            f"/api/courses/{course_id}",
            json={"title": "被跨租户修改"},
        )
        cross_asset = await second.get(f"/api/assets/{asset_id}")

    assert cross_course.status_code == 404
    assert cross_update.status_code == 404
    assert cross_asset.status_code == 404


@pytest.mark.asyncio
async def test_first_user_claims_existing_default_workspace(tmp_path):
    app = create_app(data_dir=tmp_path)
    async with await _client_for(app) as client:
        registration = await _register(client, "legacy@example.com")
        overview = await client.get("/api/knowledge/overview")

    assert registration.status_code == 201
    assert overview.status_code == 200
    payload = overview.json()
    assert payload["courseCount"] == 1
    assert payload["courses"][0]["title"] == "人工智能导论"


@pytest.mark.asyncio
async def test_logout_invalidates_session_and_login_can_start_a_new_one(tmp_path):
    app = create_app(data_dir=tmp_path)
    async with await _client_for(app) as client:
        await _register(client, "login@example.com")
        logout = await client.post("/api/auth/logout")
        assert logout.status_code == 204
        assert (await client.get("/api/auth/me")).status_code == 401

        login = await client.post(
            "/api/auth/login",
            json={
                "email": "login@example.com",
                "password": "EnterprisePass123!",
            },
        )
        assert login.status_code == 200
        assert (await client.get("/api/auth/me")).status_code == 200


@pytest.mark.asyncio
async def test_duplicate_email_and_bad_password_have_stable_errors(tmp_path):
    app = create_app(data_dir=tmp_path)
    async with await _client_for(app) as client:
        assert (await _register(client, "duplicate@example.com")).status_code == 201
        duplicate = await _register(client, "DUPLICATE@example.com")
        bad_login = await client.post(
            "/api/auth/login",
            json={
                "email": "duplicate@example.com",
                "password": "WrongPassword123!",
            },
        )

    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "email_already_registered"
    assert bad_login.status_code == 401
    assert bad_login.json()["detail"] == "invalid_credentials"


@pytest.mark.asyncio
async def test_login_attempts_are_rate_limited(tmp_path):
    app = create_app(data_dir=tmp_path)
    async with await _client_for(app) as client:
        assert (await _register(client, "rate@example.com")).status_code == 201
        await client.post("/api/auth/logout")

        statuses = []
        for _ in range(11):
            response = await client.post(
                "/api/auth/login",
                json={
                    "email": "rate@example.com",
                    "password": "WrongPassword123!",
                },
            )
            statuses.append(response.status_code)

    assert statuses[:10] == [401] * 10
    assert statuses[-1] == 429


@pytest.mark.asyncio
async def test_cross_origin_mutation_is_rejected(tmp_path):
    app = create_app(data_dir=tmp_path)
    async with await _client_for(app) as client:
        await _register(client, "origin@example.com")

        response = await client.post(
            "/api/courses",
            json={"title": "伪造跨站请求"},
            headers={"Origin": "https://evil.example"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "cross_origin_request_rejected"
