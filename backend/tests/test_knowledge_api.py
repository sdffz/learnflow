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
                "name": "知识库测试用户",
                "email": f"knowledge-{tmp_path.name}@example.com",
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


@pytest.mark.asyncio
async def test_course_upload_search_and_asset_detail(tmp_path):
    async with await _client_for(tmp_path) as client:
        overview = (await client.get("/api/knowledge/overview")).json()
        assert overview["courseCount"] == 1
        assert overview["courses"][0]["title"] == "人工智能导论"

        created = await client.post(
            "/api/courses",
            json={"title": "算法", "description": "搜索与图"},
        )
        assert created.status_code == 201
        course = created.json()

        upload = await client.post(
            f"/api/courses/{course['id']}/assets",
            files={
                "file": (
                    "bfs.md",
                    "# BFS\n\n广度优先搜索使用队列。".encode(),
                    "text/markdown",
                )
            },
            data={"title": "BFS 课堂笔记", "tags": "图论,搜索"},
        )
        assert upload.status_code == 201
        asset = upload.json()
        assert asset["courseTitle"] == "算法"
        assert asset["knowledgeCount"] == 1
        assert asset["status"] == "ready"
        assert asset["chunks"][0]["title"] == "BFS"

        detail = await client.get(f"/api/assets/{asset['id']}")
        assert detail.status_code == 200
        assert detail.json()["chunks"][0]["courseTitle"] == "算法"

        source_file = await client.get(f"/api/assets/{asset['id']}/file")
        assert source_file.status_code == 200
        assert "广度优先搜索" in source_file.text

        search = await client.get(
            "/api/knowledge/search",
            params={"q": "队列", "tag": "图论"},
        )
        assert search.status_code == 200
        payload = search.json()
        assert payload["total"] == 1
        assert payload["items"][0]["assetTitle"] == "BFS 课堂笔记"


@pytest.mark.asyncio
async def test_notes_course_update_and_delete_flow(tmp_path):
    async with await _client_for(tmp_path) as client:
        course = (
            await client.post("/api/courses", json={"title": "编译原理"})
        ).json()
        note_response = await client.post(
            f"/api/courses/{course['id']}/notes",
            json={
                "title": "语法分析",
                "content": "语法分析把词法单元组织成语法树。",
                "tags": ["编译", "语法树"],
            },
        )
        assert note_response.status_code == 201
        note = note_response.json()
        assert note["chunks"][0]["excerpt"]

        updated = await client.patch(
            f"/api/courses/{course['id']}",
            json={"description": "词法、语法与语义分析"},
        )
        assert updated.status_code == 200
        assert updated.json()["description"] == "词法、语法与语义分析"

        deleted_asset = await client.delete(f"/api/assets/{note['id']}")
        assert deleted_asset.status_code == 204
        assert (await client.get(f"/api/assets/{note['id']}")).status_code == 404

        deleted_course = await client.delete(f"/api/courses/{course['id']}")
        assert deleted_course.status_code == 204
        assert (await client.get(f"/api/courses/{course['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_upload_rejects_unsupported_and_empty_files(tmp_path):
    async with await _client_for(tmp_path) as client:
        course = (
            await client.get("/api/courses")
        ).json()["items"][0]

        unsupported = await client.post(
            f"/api/courses/{course['id']}/assets",
            files={"file": ("video.mp4", b"data", "video/mp4")},
        )
        empty = await client.post(
            f"/api/courses/{course['id']}/assets",
            files={"file": ("empty.md", b"", "text/markdown")},
        )

    assert unsupported.status_code == 422
    assert unsupported.json()["detail"] == "unsupported_file_type"
    assert empty.status_code == 422
    assert empty.json()["detail"] == "empty_file"


@pytest.mark.asyncio
async def test_upload_rejects_file_with_spoofed_image_type(tmp_path):
    async with await _client_for(tmp_path) as client:
        await client.post(
            "/api/auth/register",
            json={
                "name": "上传测试",
                "email": "upload@example.com",
                "password": "EnterprisePass123!",
            },
        )
        course = (await client.get("/api/courses")).json()["items"][0]
        response = await client.post(
            f"/api/courses/{course['id']}/assets",
            files={
                "file": (
                    "fake.png",
                    b"<html><script>alert(1)</script></html>",
                    "image/png",
                )
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_file_content"
