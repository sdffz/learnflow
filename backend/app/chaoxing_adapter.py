from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import unquote, urljoin, urlparse
from uuid import uuid4

import httpx

from .ingestion import SUPPORTED_EXTENSIONS
from .learning_domain import FinishLogin, PreviewCourse, PreviewFile, QrLoginTicket

DEFAULT_LOGIN_URL = (
    "https://passport2.chaoxing.com/login"
    "?fid=&refer=http%3A%2F%2Fi.mooc.chaoxing.com%2Fspace%2Findex"
)
DEFAULT_STATUS_URL = "https://passport2.chaoxing.com/getauthstatus/v2"
DEFAULT_COURSE_API_URL = (
    "https://mooc1-api.chaoxing.com/mycourse/backclazzdata?view=json&rss=1"
)
DEFAULT_FOLDER_URL = (
    "https://mooc1.chaoxing.com/mycourse/studentcourse"
    "?courseId={course_id}&clazzid={class_id}&vc=1&cpi={cpi}"
)
MAX_IMPORT_FILE_BYTES = 100 * 1024 * 1024
MAX_QR_BYTES = 1024 * 1024
MAX_CATALOG_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_CATALOG_TOTAL_PAGES = 40
CATALOG_DEADLINE_SECONDS = 45
MAX_CATALOG_PAGES_PER_COURSE = 8
LOGIN_TTL = timedelta(minutes=5)
ALLOWED_HOST_SUFFIXES = (".chaoxing.com", ".cldisk.com")
VIDEO_EXTENSIONS = {".mp4", ".m3u8", ".flv", ".avi", ".mov", ".mkv", ".webm"}


class ChaoxingAdapterError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _host_is_allowed(host: str, allowed_hosts: set[str] | None) -> bool:
    normalized = host.casefold().rstrip(".")
    if normalized in {"localhost"}:
        return False
    try:
        ipaddress.ip_address(normalized)
    except ValueError:
        pass
    else:
        return False
    if allowed_hosts and normalized in {item.casefold() for item in allowed_hosts}:
        return True
    return any(
        normalized == suffix.lstrip(".") or normalized.endswith(suffix)
        for suffix in ALLOWED_HOST_SUFFIXES
    )


def validate_chaoxing_url(
    value: str,
    *,
    allowed_hosts: set[str] | None = None,
) -> httpx.URL:
    try:
        parsed = httpx.URL(value)
    except (httpx.InvalidURL, TypeError) as exc:
        raise ChaoxingAdapterError("invalid_upstream_url") from exc
    if parsed.scheme != "https":
        raise ChaoxingAdapterError("upstream_host_not_allowed")
    if parsed.userinfo:
        raise ChaoxingAdapterError("upstream_host_not_allowed")
    if not _host_is_allowed(parsed.host, allowed_hosts):
        raise ChaoxingAdapterError("upstream_host_not_allowed")
    return parsed


@dataclass
class _LoginState:
    id: str
    client: httpx.Client
    uuid: str
    enc: str
    qr_png: bytes
    expires_at: datetime
    revision: int = 0
    status: str = "pending"
    remote_nickname: str | None = None
    message: str | None = None
    cookies: dict[str, str] | None = None


@dataclass
class _Anchor:
    href: str
    text: str
    tag: str = "a"


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[_Anchor] = []
        self._active: tuple[str, str] | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in {"a", "iframe", "frame"}:
            return
        values = dict(attrs)
        href = values.get("href") or values.get("src") or ""
        if href:
            if tag == "a":
                self._active = (href, tag)
                self._text = []
            else:
                self.links.append(_Anchor(href=href, text="", tag=tag))

    def handle_data(self, data: str) -> None:
        if self._active:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._active:
            return
        href, active_tag = self._active
        self.links.append(
            _Anchor(
                href=href,
                text=" ".join("".join(self._text).split()),
                tag=active_tag,
            )
        )
        self._active = None
        self._text = []


def _attr(tag: str, name: str) -> str | None:
    match = re.search(
        rf"""\b{re.escape(name)}\s*=\s*["']([^"']*)["']""",
        tag,
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match else None


def _hidden_value(html: str, element_id: str) -> str | None:
    for tag in re.findall(r"<input\b[^>]*>", html, flags=re.IGNORECASE):
        if _attr(tag, "id") == element_id:
            return _attr(tag, "value")
    return None


def _qr_source(html: str) -> str | None:
    for tag in re.findall(r"<img\b[^>]*>", html, flags=re.IGNORECASE):
        if _attr(tag, "id") == "quickCode":
            return _attr(tag, "src")
    return None


def _file_extension(value: str) -> str:
    name = unquote(urlparse(value).path.rsplit("/", 1)[-1])
    return Path(name).suffix.casefold()


def _display_name(anchor: _Anchor) -> str:
    if anchor.text.strip():
        return anchor.text.strip()[:180]
    name = unquote(urlparse(anchor.href).path.rsplit("/", 1)[-1])
    return name[:180] or "未命名资料"


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _first_string(mapping: dict, names: tuple[str, ...]) -> str:
    for name in names:
        value = mapping.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _course_cards(payload: dict) -> list[dict]:
    cards: list[dict] = []
    seen: set[str] = set()
    for mapping in _walk_dicts(payload):
        title = _first_string(mapping, ("name", "courseName", "title"))
        course_id = _first_string(
            mapping,
            ("courseid", "courseId", "id"),
        )
        class_id = _first_string(mapping, ("clazzid", "classId", "clazzId"))
        if not title or not course_id or not class_id:
            continue
        key = f"{course_id}:{class_id}"
        if key in seen:
            continue
        seen.add(key)
        cards.append(mapping)
    return cards


def _bounded_get(
    client: httpx.Client,
    url: str,
    *,
    allowed_hosts: set[str] | None,
    max_bytes: int,
    headers: dict[str, str] | None = None,
) -> tuple[str, str]:
    current = url
    for _redirect in range(4):
        safe_url = validate_chaoxing_url(
            current,
            allowed_hosts=allowed_hosts,
        )
        with client.stream(
            "GET",
            safe_url,
            headers=headers,
            follow_redirects=False,
        ) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise ChaoxingAdapterError("invalid_upstream_redirect")
                current = urljoin(str(safe_url), location)
                continue
            response.raise_for_status()
            content_length = int(
                response.headers.get("content-length", "0") or 0
            )
            if content_length > max_bytes:
                raise ChaoxingAdapterError("upstream_response_too_large")
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes(64 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise ChaoxingAdapterError("upstream_response_too_large")
                chunks.append(chunk)
            payload = b"".join(chunks)
            encoding = response.charset_encoding or "utf-8"
            try:
                text = payload.decode(encoding)
            except (LookupError, UnicodeDecodeError):
                text = payload.decode("utf-8", errors="replace")
            return str(response.url), text
    raise ChaoxingAdapterError("too_many_upstream_redirects")


class ChaoxingAdapter:
    def __init__(
        self,
        *,
        enabled: bool = True,
        client: httpx.Client | None = None,
        login_url: str = DEFAULT_LOGIN_URL,
        status_url: str = DEFAULT_STATUS_URL,
        course_api_url: str = DEFAULT_COURSE_API_URL,
        folder_url_template: str = DEFAULT_FOLDER_URL,
        allowed_hosts: set[str] | None = None,
    ):
        self.enabled = enabled
        self.client = client
        self.login_url = login_url
        self.status_url = status_url
        self.course_api_url = course_api_url
        self.folder_url_template = folder_url_template
        self.allowed_hosts = allowed_hosts
        self._logins: dict[str, _LoginState] = {}
        self._lock = RLock()

    def _new_client(self) -> httpx.Client:
        if self.client is not None:
            return self.client
        return httpx.Client(
            timeout=httpx.Timeout(20.0, connect=8.0),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )

    def start_login(self) -> QrLoginTicket:
        if not self.enabled:
            raise ChaoxingAdapterError("connector_disabled")
        self.sweep_expired()
        login_id = uuid4().hex
        state = self._create_login_state(login_id=login_id, revision=0)
        with self._lock:
            self._logins[login_id] = state
        return QrLoginTicket(
            id=state.id,
            qr_png=state.qr_png,
            expires_at=state.expires_at.isoformat(),
            revision=state.revision,
        )

    def refresh_login(self, login_id: str) -> QrLoginTicket:
        self.sweep_expired()
        with self._lock:
            previous = self._logins.get(login_id)
        if previous is None:
            raise ChaoxingAdapterError("login_not_found")
        revision = previous.revision + 1 if previous else 0
        state = self._create_login_state(login_id=login_id, revision=revision)
        with self._lock:
            current = self._logins.get(login_id)
            if current is None:
                stale = state
                state = None
            else:
                self._logins[login_id] = state
                stale = current
        if state is None:
            if self.client is None:
                stale.client.close()
            raise ChaoxingAdapterError("login_not_found")
        if stale and stale is not state and self.client is None:
            stale.client.close()
        return QrLoginTicket(
            id=state.id,
            qr_png=state.qr_png,
            expires_at=state.expires_at.isoformat(),
            revision=state.revision,
        )

    def _create_login_state(self, *, login_id: str, revision: int) -> _LoginState:
        client = self._new_client()
        try:
            response = client.get(self.login_url)
            response.raise_for_status()
            html = response.text
            login_uuid = _hidden_value(html, "uuid")
            enc = _hidden_value(html, "enc")
            qr_source = _qr_source(html)
            if not login_uuid or not enc or not qr_source:
                raise ChaoxingAdapterError("upstream_changed")
            qr_url = urljoin(str(response.url), qr_source)
            qr_response = client.get(qr_url, headers={"Referer": str(response.url)})
            qr_response.raise_for_status()
            if not qr_response.content.startswith(b"\x89PNG"):
                raise ChaoxingAdapterError("upstream_changed")
            if len(qr_response.content) > MAX_QR_BYTES:
                raise ChaoxingAdapterError("upstream_response_too_large")
            return _LoginState(
                id=login_id,
                client=client,
                uuid=login_uuid,
                enc=enc,
                qr_png=qr_response.content,
                expires_at=datetime.now(UTC) + LOGIN_TTL,
                revision=revision,
            )
        except Exception:
            if self.client is None:
                client.close()
            raise

    def qr_image(self, login_id: str) -> bytes:
        with self._lock:
            state = self._logins.get(login_id)
            expired = bool(
                state and datetime.now(UTC) >= state.expires_at
            )
            if expired:
                state = self._logins.pop(login_id)
        if state and expired:
            if self.client is None:
                state.client.close()
            raise ChaoxingAdapterError("login_expired")
        self.sweep_expired()
        state = self._require_login(login_id)
        return state.qr_png

    def login_status(self, login_id: str) -> FinishLogin:
        self.sweep_expired()
        state = self._require_login(login_id)
        with self._lock:
            expired = (
                datetime.now(UTC) >= state.expires_at
                and state.status != "connected"
            )
            if expired:
                self._logins.pop(login_id, None)
        if expired:
            if self.client is None:
                state.client.close()
            return FinishLogin(status="expired", message="login_expired")
        if state.status in {"cancelled", "expired", "verification_required"}:
            return FinishLogin(
                status=state.status,
                remote_nickname=state.remote_nickname,
                message=state.message,
            )
        if state.status == "connected":
            return FinishLogin(
                status="connected",
                remote_nickname=state.remote_nickname,
                message=state.message,
            )
        try:
            response = state.client.post(
                self.status_url,
                data={
                    "enc": state.enc,
                    "uuid": state.uuid,
                    "doubleFactorLogin": "0",
                    "forbidotherlogin": "0",
                },
                headers={"Referer": self.login_url},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            state.message = "upstream_unavailable"
            return FinishLogin(status=state.status, message=state.message)
        if bool(payload.get("status")):
            with self._lock:
                if self._logins.get(login_id) is not state:
                    raise ChaoxingAdapterError("login_not_found")
                state.status = "connected"
                state.remote_nickname = (
                    str(payload.get("nickname") or "").strip() or None
                )
                state.cookies = {
                    cookie.name: cookie.value
                    for cookie in state.client.cookies.jar
                }
            return FinishLogin(status="connected", remote_nickname=state.remote_nickname)
        if payload.get("containTwoFactorLogin") or payload.get("doubleFactorLogin"):
            with self._lock:
                if self._logins.get(login_id) is not state:
                    raise ChaoxingAdapterError("login_not_found")
                state.status = "verification_required"
                state.message = "verification_required"
            return FinishLogin(status="verification_required", message=state.message)
        response_type = payload.get("type")
        if response_type == 4:
            with self._lock:
                if self._logins.get(login_id) is not state:
                    raise ChaoxingAdapterError("login_not_found")
                state.status = "confirming"
                state.remote_nickname = (
                    str(payload.get("nickname") or "").strip() or None
                )
            return FinishLogin(status="confirming", remote_nickname=state.remote_nickname)
        if response_type == 6:
            with self._lock:
                if self._logins.get(login_id) is not state:
                    raise ChaoxingAdapterError("login_not_found")
                state.status = "cancelled"
                state.message = "login_cancelled"
            return FinishLogin(status="cancelled", message=state.message)
        if response_type == 2:
            with self._lock:
                if self._logins.get(login_id) is not state:
                    raise ChaoxingAdapterError("login_not_found")
                state.status = "expired"
                state.message = "login_expired"
            return FinishLogin(status="expired", message=state.message)
        if response_type == 7:
            with self._lock:
                if self._logins.get(login_id) is not state:
                    raise ChaoxingAdapterError("login_not_found")
                state.status = "verification_required"
                state.message = str(
                    payload.get("mes") or "verification_required"
                )
            return FinishLogin(status="verification_required", message=state.message)
        with self._lock:
            if self._logins.get(login_id) is not state:
                raise ChaoxingAdapterError("login_not_found")
            state.status = "pending"
        return FinishLogin(status="pending")

    def take_cookies(self, login_id: str) -> dict[str, str]:
        with self._lock:
            state = self._logins.get(login_id)
            if state is None:
                raise ChaoxingAdapterError("login_not_found")
            if state.status != "connected" or not state.cookies:
                raise ChaoxingAdapterError("login_not_connected")
            cookies = dict(state.cookies)
            self._logins.pop(login_id, None)
        if self.client is None:
            state.client.close()
        return cookies

    def cancel_login(self, login_id: str) -> None:
        self._drop_login(login_id)

    def sweep_expired(self) -> int:
        now = datetime.now(UTC)
        with self._lock:
            expired_ids = [
                login_id
                for login_id, state in self._logins.items()
                if now >= state.expires_at and state.status != "connected"
            ]
            expired_states = [
                self._logins.pop(login_id)
                for login_id in expired_ids
            ]
        if self.client is None:
            for state in expired_states:
                state.client.close()
        return len(expired_states)

    def _require_login(self, login_id: str) -> _LoginState:
        with self._lock:
            state = self._logins.get(login_id)
        if state is None:
            raise ChaoxingAdapterError("login_not_found")
        return state

    def _drop_login(self, login_id: str) -> None:
        with self._lock:
            state = self._logins.pop(login_id, None)
        if state and self.client is None:
            state.client.close()

    def _client_with_cookies(self, cookies: dict[str, str]) -> httpx.Client:
        client = self._new_client()
        client.cookies.update(cookies)
        return client

    def catalog(self, cookies: dict[str, str]) -> list[PreviewCourse]:
        client = self._client_with_cookies(cookies)
        owned = self.client is None
        try:
            _, response_text = _bounded_get(
                client,
                self.course_api_url,
                allowed_hosts=self.allowed_hosts,
                max_bytes=MAX_CATALOG_RESPONSE_BYTES,
            )
            try:
                payload = json.loads(response_text)
            except (TypeError, ValueError):
                payload = {}
            if isinstance(payload, dict) and payload.get("status") is False:
                message = str(payload.get("msg") or payload.get("errorMsg") or "")
                if "登录" in message:
                    raise ChaoxingAdapterError("session_expired")
                raise ChaoxingAdapterError("upstream_changed")
            cards = _course_cards(payload if isinstance(payload, dict) else {})
            deadline = time.monotonic() + CATALOG_DEADLINE_SECONDS
            budget = {"pages": 0}
            return [
                self._course_from_card(
                    client,
                    card,
                    cookies,
                    deadline=deadline,
                    budget=budget,
                )
                for card in cards
            ]
        finally:
            if owned:
                client.close()

    def _course_from_card(
        self,
        client: httpx.Client,
        card: dict,
        cookies: dict[str, str],
        *,
        deadline: float,
        budget: dict[str, int],
    ) -> PreviewCourse:
        course_id = _first_string(card, ("courseid", "courseId", "id"))
        class_id = _first_string(card, ("clazzid", "classId", "clazzId"))
        cpi = _first_string(card, ("cpi", "cpiId"))
        title = _first_string(card, ("name", "courseName", "title")) or "未命名课程"
        teacher = _first_string(card, ("teacherfactor", "teacher", "teacherName"))
        candidates: list[str] = []
        card_url = _first_string(card, ("url", "courseUrl"))
        if card_url:
            candidates.append(card_url)
        if class_id:
            candidates.append(
                self.folder_url_template.format(
                    course_id=course_id,
                    class_id=class_id,
                    cpi=cpi,
                )
            )
        documents: list[PreviewFile] = []
        videos: list[str] = []
        seen_documents: set[str] = set()
        seen_videos: set[str] = set()
        queue = [(url, 0) for url in candidates if url]
        visited: set[str] = set()
        pages = 0
        while queue and pages < MAX_CATALOG_PAGES_PER_COURSE:
            if time.monotonic() >= deadline:
                raise ChaoxingAdapterError("upstream_timeout")
            if budget["pages"] >= MAX_CATALOG_TOTAL_PAGES:
                raise ChaoxingAdapterError("catalog_budget_exceeded")
            candidate, depth = queue.pop(0)
            try:
                safe_page = validate_chaoxing_url(
                    candidate,
                    allowed_hosts=self.allowed_hosts,
                )
            except ChaoxingAdapterError:
                continue
            normalized_page = str(safe_page)
            if normalized_page in visited:
                continue
            visited.add(normalized_page)
            pages += 1
            budget["pages"] += 1
            try:
                response_url, response_text = _bounded_get(
                    client,
                    normalized_page,
                    allowed_hosts=self.allowed_hosts,
                    max_bytes=MAX_CATALOG_RESPONSE_BYTES,
                    headers={"Referer": self.course_api_url},
                )
            except ChaoxingAdapterError:
                raise
            except httpx.HTTPError:
                continue
            if "登录" in response_text and "二维码" in response_text:
                raise ChaoxingAdapterError("session_expired")
            parser = _LinkParser()
            try:
                parser.feed(response_text)
            except Exception:
                continue
            for anchor in parser.links:
                link = urljoin(response_url, anchor.href)
                extension = _file_extension(link)
                if extension in VIDEO_EXTENSIONS:
                    try:
                        safe_video = str(
                            validate_chaoxing_url(
                                link,
                                allowed_hosts=self.allowed_hosts,
                            )
                        )
                    except ChaoxingAdapterError:
                        continue
                    if safe_video not in seen_videos:
                        seen_videos.add(safe_video)
                        videos.append(safe_video)
                    continue
                if extension and (
                    extension in SUPPORTED_EXTENSIONS
                    or extension
                    in {
                        ".zip",
                        ".rar",
                        ".7z",
                        ".xls",
                        ".xlsx",
                        ".ppt",
                        ".doc",
                        ".wps",
                    }
                ):
                    try:
                        safe_file = str(
                            validate_chaoxing_url(
                                link,
                                allowed_hosts=self.allowed_hosts,
                            )
                        )
                    except ChaoxingAdapterError:
                        continue
                    file_id = hashlib.sha256(
                        f"{course_id}:{safe_file}".encode()
                    ).hexdigest()[:24]
                    if file_id in seen_documents:
                        continue
                    seen_documents.add(file_id)
                    supported = extension in SUPPORTED_EXTENSIONS
                    documents.append(
                        PreviewFile(
                            id=file_id,
                            name=_display_name(anchor),
                            extension=extension,
                            size_bytes=0,
                            supported=supported,
                            excluded_reason=(
                                None if supported else "unsupported_file_type"
                            ),
                            remote_url=safe_file,
                        )
                    )
                    continue
                if depth >= 1 or not extension:
                    text = anchor.text.casefold()
                    if not extension and any(
                        word in text for word in ("资料", "文件", "课程", "附件")
                    ):
                        try:
                            safe_next = str(
                                validate_chaoxing_url(
                                    link,
                                    allowed_hosts=self.allowed_hosts,
                                )
                            )
                        except ChaoxingAdapterError:
                            continue
                        queue.append((safe_next, depth + 1))
        return PreviewCourse(
            id=course_id,
            title=title,
            teacher=teacher,
            documents=documents,
            video_links=videos,
        )

    def download(
        self,
        cookies: dict[str, str],
        source_url: str,
        destination: Path,
        *,
        expected_size: int = 0,
    ) -> str:
        if expected_size > MAX_IMPORT_FILE_BYTES:
            destination.unlink(missing_ok=True)
            raise ChaoxingAdapterError("file_too_large")
        client = self._client_with_cookies(cookies)
        owned = self.client is None
        temporary = destination.with_suffix(destination.suffix + ".part")
        temporary.parent.mkdir(parents=True, exist_ok=True)
        temporary.unlink(missing_ok=True)
        digest = hashlib.sha256()
        size = 0
        current = source_url
        try:
            for _redirect in range(4):
                safe_url = validate_chaoxing_url(
                    current,
                    allowed_hosts=self.allowed_hosts,
                )
                with client.stream(
                    "GET",
                    safe_url,
                    headers={"Referer": self.course_api_url},
                    follow_redirects=False,
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise ChaoxingAdapterError("invalid_upstream_redirect")
                        current = urljoin(str(safe_url), location)
                        continue
                    response.raise_for_status()
                    content_length = int(response.headers.get("content-length", "0") or 0)
                    if content_length > MAX_IMPORT_FILE_BYTES:
                        raise ChaoxingAdapterError("file_too_large")
                    with temporary.open("wb") as stream:
                        for chunk in response.iter_bytes(64 * 1024):
                            size += len(chunk)
                            if size > MAX_IMPORT_FILE_BYTES:
                                raise ChaoxingAdapterError("file_too_large")
                            digest.update(chunk)
                            stream.write(chunk)
                    if size <= 0:
                        raise ChaoxingAdapterError("empty_file")
                    os.replace(temporary, destination)
                    return digest.hexdigest()
            raise ChaoxingAdapterError("too_many_upstream_redirects")
        except Exception:
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            raise
        finally:
            if owned:
                client.close()


def decode_connector_key(value: str | None) -> bytes | None:
    if not value:
        return None
    import base64

    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except ValueError:
        return None
    return decoded if len(decoded) == 32 else None


def wait_for_retry(seconds: float) -> None:
    time.sleep(seconds)
