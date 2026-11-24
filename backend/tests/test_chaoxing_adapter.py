from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

import app.chaoxing_adapter as adapter_module
from app.chaoxing_adapter import ChaoxingAdapter, validate_chaoxing_url

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _adapter(handler) -> ChaoxingAdapter:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return ChaoxingAdapter(
        client=client,
        login_url="https://passport2.chaoxing.test/login",
        status_url="https://passport2.chaoxing.test/getauthstatus/v2",
        course_api_url="https://mooc1-api.chaoxing.test/mycourse/backclazzdata",
        folder_url_template=(
            "https://mooc1.chaoxing.test/mycourse/studentcourse"
            "?courseId={course_id}&clazzid={class_id}&vc=1&cpi={cpi}"
        ),
        allowed_hosts={"passport2.chaoxing.test", "mooc1-api.chaoxing.test", "mooc1.chaoxing.test"},
    )


def test_qr_login_polls_to_connected_state():
    calls = {"status": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(
                200,
                text="""
                <input type="hidden" id="uuid" value="uuid-1">
                <input type="hidden" id="enc" value="enc-1">
                <img id="quickCode" src="/createqr?uuid=uuid-1&fid=-1">
                """,
                headers={"content-type": "text/html"},
            )
        if request.url.path == "/createqr":
            return httpx.Response(200, content=PNG_BYTES, headers={"content-type": "image/png"})
        if request.url.path == "/getauthstatus/v2":
            calls["status"] += 1
            if calls["status"] == 1:
                return httpx.Response(
                    200,
                    json={"status": False},
                    headers={"set-cookie": "auth=session-token; Path=/"},
                )
            if calls["status"] == 2:
                return httpx.Response(
                    200,
                    json={"status": False, "type": 4, "nickname": "张同学"},
                    headers={"set-cookie": "auth=session-token; Path=/"},
                )
            return httpx.Response(
                200,
                json={"status": True, "nickname": "张同学"},
                headers={"set-cookie": "auth=session-token; Path=/"},
            )
        raise AssertionError(f"unexpected request: {request.url}")

    adapter = _adapter(handler)
    started = adapter.start_login()

    assert started.qr_png.startswith(b"\x89PNG")
    assert adapter.login_status(started.id).status == "pending"
    assert adapter.login_status(started.id).status == "confirming"
    finished = adapter.login_status(started.id)
    assert finished.status == "connected"
    assert finished.remote_nickname == "张同学"
    assert adapter.take_cookies(started.id) == {"auth": "session-token"}


def test_login_expiry_and_refresh():
    revisions = {"qr": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(
                200,
                text=(
                    '<input id="uuid" value="uuid-1">'
                    '<input id="enc" value="enc-1">'
                    '<img id="quickCode" src="/createqr?uuid=uuid-1">'
                ),
            )
        if request.url.path == "/createqr":
            revisions["qr"] += 1
            return httpx.Response(200, content=PNG_BYTES, headers={"content-type": "image/png"})
        raise AssertionError(f"unexpected request: {request.url}")

    adapter = _adapter(handler)
    ticket = adapter.start_login()
    refreshed = adapter.refresh_login(ticket.id)

    assert refreshed.revision == 1
    assert revisions["qr"] == 2


def test_expired_login_sessions_are_swept(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(
                200,
                text=(
                    '<input id="uuid" value="uuid-1">'
                    '<input id="enc" value="enc-1">'
                    '<img id="quickCode" src="/createqr?uuid=uuid-1">'
                ),
            )
        return httpx.Response(200, content=PNG_BYTES)

    monkeypatch.setattr(adapter_module, "LOGIN_TTL", adapter_module.timedelta(seconds=-1))
    adapter = _adapter(handler)
    ticket = adapter.start_login()

    assert adapter.sweep_expired() == 1
    with pytest.raises(ValueError, match="login_not_found"):
        adapter.login_status(ticket.id)


def test_concurrent_qr_sweep_is_thread_safe():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(
                200,
                text=(
                    '<input id="uuid" value="uuid-1">'
                    '<input id="enc" value="enc-1">'
                    '<img id="quickCode" src="/createqr?uuid=uuid-1">'
                ),
            )
        return httpx.Response(200, content=PNG_BYTES)

    adapter = _adapter(handler)
    tickets = [adapter.start_login() for _ in range(3)]
    for ticket in tickets:
        adapter._logins[ticket.id].expires_at = (
            datetime.now(UTC) - timedelta(seconds=1)
        )

    with ThreadPoolExecutor(max_workers=3) as executor:
        removed = list(executor.map(lambda _: adapter.sweep_expired(), range(6)))

    assert sum(removed) == 3


def test_catalog_normalizes_courses_and_document_links():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "mooc1-api.chaoxing.test":
            return httpx.Response(
                200,
                json={
                    "channelList": [
                        {
                            "content": {
                                "course": {
                                    "data": [
                                        {
                                            "name": "高等数学",
                                            "teacherfactor": "张老师",
                                            "courseid": "course-1",
                                            "clazzid": "class-1",
                                            "cpi": "cpi-1",
                                            "url": "https://mooc1.chaoxing.test/course/1",
                                        }
                                    ]
                                }
                            }
                        }
                    ]
                },
            )
        if request.url.host == "mooc1.chaoxing.test":
            return httpx.Response(
                200,
                text="""
                <a href="/files/chapter-1.pdf">第一章.pdf</a>
                <a href="/files/slides.pptx">第二章.pptx</a>
                <a href="https://mooc1.chaoxing.test/video/1.mp4">课程视频</a>
                """,
            )
        raise AssertionError(f"unexpected request: {request.url}")

    adapter = _adapter(handler)
    # 章节与附件只在被显式指定时抓取
    courses = adapter.catalog(
        {"auth": "session-token"}, deep_course_ids={"course-1:class-1"}
    )

    assert len(courses) == 1
    assert courses[0].title == "高等数学"
    assert courses[0].teacher == "张老师"
    assert [file.name for file in courses[0].documents] == ["第一章.pdf", "第二章.pptx"]
    assert courses[0].documents[0].remote_url.endswith("/files/chapter-1.pdf")
    assert courses[0].video_links == ["https://mooc1.chaoxing.test/video/1.mp4"]


def test_catalog_maps_unsupported_files_with_reason():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "mooc1-api.chaoxing.test":
            return httpx.Response(
                200,
                json={
                    "channelList": [
                        {
                            "content": {
                                "course": {
                                    "data": [
                                        {
                                            "name": "物理",
                                            "courseid": "c1",
                                            "clazzid": "k1",
                                            "url": "https://mooc1.chaoxing.test/course/2",
                                        }
                                    ]
                                }
                            }
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            text='<a href="/files/archive.zip">资料包.zip</a>',
        )

    adapter = _adapter(handler)
    files = adapter.catalog(
        {"auth": "session-token"}, deep_course_ids={"c1:k1"}
    )[0].documents

    assert files[0].supported is False
    assert files[0].excluded_reason == "unsupported_file_type"


def test_catalog_response_size_is_bounded(monkeypatch):
    monkeypatch.setattr(adapter_module, "MAX_CATALOG_RESPONSE_BYTES", 32)
    adapter = _adapter(
        lambda request: httpx.Response(
            200,
            content=b'{"channelList": [], "padding": "' + b"x" * 80 + b'"}',
        )
    )

    with pytest.raises(ValueError, match="upstream_response_too_large"):
        adapter.catalog({"auth": "session-token"})


def test_catalog_has_global_page_budget(monkeypatch):
    cards = [
        {
            "name": f"课程{i}",
            "courseid": f"course-{i}",
            "clazzid": f"class-{i}",
            "url": f"https://mooc1.chaoxing.test/course/{i}",
        }
        for i in range(2)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "mooc1-api.chaoxing.test":
            return httpx.Response(
                200,
                json={"channelList": [{"content": {"course": {"data": cards}}}]},
            )
        return httpx.Response(200, text="<html></html>")

    monkeypatch.setattr(adapter_module, "MAX_CATALOG_TOTAL_PAGES", 1)
    adapter = _adapter(handler)

    with pytest.raises(ValueError, match="catalog_budget_exceeded"):
        adapter.catalog(
            {"auth": "session-token"},
            deep_course_ids={"course-0:class-0", "course-1:class-1"},
        )


def test_catalog_deadline_fails_closed(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "mooc1-api.chaoxing.test":
            return httpx.Response(
                200,
                json={
                    "channelList": [
                        {
                            "content": {
                                "course": {
                                    "data": [
                                        {
                                            "name": "课程",
                                            "courseid": "course",
                                            "clazzid": "class",
                                            "url": "https://mooc1.chaoxing.test/course/1",
                                        }
                                    ]
                                }
                            }
                        }
                    ]
                },
            )
        return httpx.Response(200, text="<html></html>")

    monkeypatch.setattr(adapter_module, "CATALOG_DEADLINE_SECONDS", 0)
    adapter = _adapter(handler)

    with pytest.raises(ValueError, match="upstream_timeout"):
        adapter.catalog({"auth": "session-token"}, deep_course_ids={"course:class"})


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/private.pdf",
        "https://127.0.0.1/private.pdf",
        "https://8.8.8.8/public.pdf",
    ],
)
def test_ip_addresses_are_rejected(url):
    with pytest.raises(ValueError, match="upstream_host_not_allowed"):
        validate_chaoxing_url(url)


def test_oversize_download_is_deleted(tmp_path):
    adapter = _adapter(lambda request: httpx.Response(200, content=b"x"))

    with pytest.raises(ValueError, match="file_too_large"):
        adapter.download(
            {"auth": "session-token"},
            "https://mooc1.chaoxing.test/files/too-large.pdf",
            tmp_path / "too-large.pdf",
            expected_size=101 * 1024 * 1024,
        )

    assert not (tmp_path / "too-large.pdf").exists()


def test_download_rejects_redirect_to_private_host(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "http://127.0.0.1/private.pdf"},
        )

    adapter = _adapter(handler)

    with pytest.raises(ValueError, match="upstream_host_not_allowed"):
        adapter.download(
            {"auth": "session-token"},
            "https://mooc1.chaoxing.test/files/a.pdf",
            tmp_path / "a.pdf",
            expected_size=10,
        )


def test_download_writes_checksum_and_filename(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"%PDF-1.4 sample",
            headers={"content-type": "application/pdf"},
        )

    adapter = _adapter(handler)
    destination = tmp_path / "document.pdf"
    checksum = adapter.download(
        {"auth": "session-token"},
        "https://mooc1.chaoxing.test/files/a.pdf",
        destination,
        expected_size=14,
    )

    assert destination.read_bytes() == b"%PDF-1.4 sample"
    assert len(checksum) == 64
    assert Path(destination).stat().st_size == 15


def test_catalog_reads_the_real_backclazzdata_shape():
    """The upstream nests the class id in content and the course id deeper.

    Regression: /mycourse/backclazzdata returns
    ``channelList[i].content.id`` (class) with the course under
    ``content.course.data[0].id``. Neither key is named courseid/clazzid, so a
    naive walker produced an empty catalog for a user with 37 enrolments.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "mooc1-api.chaoxing.test":
            return httpx.Response(
                200,
                json={
                    "result": 1,
                    "msg": "获取成功",
                    "channelList": [
                        {
                            "cataName": "课程",
                            "cpi": 496659214,
                            "id": 0,
                            "key": 155189510,
                            "content": {
                                "id": 155189510,
                                "name": "202116530-002",
                                "cpi": 496659214,
                                "studentcount": 49,
                                "course": {
                                    "data": [
                                        {
                                            "id": 267280152,
                                            "name": "大学生职业生涯规划",
                                            "teacherfactor": "洪云 等",
                                            "belongSchoolId": "1765",
                                        }
                                    ]
                                },
                            },
                        },
                        {
                            "cataName": "课程",
                            "content": {
                                "id": 153362349,
                                "name": "算法分析与设计-01",
                                "cpi": 496659214,
                                "course": {
                                    "data": [
                                        {
                                            "id": 266595280,
                                            "name": "算法分析与设计",
                                            "teacherfactor": "雍真",
                                        }
                                    ]
                                },
                            },
                        },
                        {"cataName": "专题", "content": {"id": 1}},
                    ],
                },
            )
        if request.url.host == "mooc1.chaoxing.test":
            return httpx.Response(200, text="<a href='/files/a.pdf'>a.pdf</a>")
        raise AssertionError(f"unexpected request: {request.url}")

    adapter = _adapter(handler)
    courses = adapter.catalog({"auth": "session-token"})

    assert [course.title for course in courses] == [
        "大学生职业生涯规划",
        "算法分析与设计",
    ]
    assert courses[0].teacher == "洪云 等"
    assert courses[1].teacher == "雍真"
    assert courses[0].id == "267280152:155189510"
