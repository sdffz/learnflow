# 学习通扫码导入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为知序增加学习通扫码授权、课程文档预览、选择性导入、持久化同步任务和 ZIP 备用导入。

**Architecture:** 新增独立连接器模块，服务端代理学习通官方二维码和加密短期会话，选择结果写入持久化任务后由单节点后台执行器导入现有 `KnowledgeStore`。前端通过同一套向导在桌面和手机完成扫码、预览、映射、同步和失败重试。

**Tech Stack:** FastAPI、Pydantic、httpx、AES-GCM（cryptography）、SQLite WAL、React、TypeScript、Vitest、Playwright

## Global Constraints

- 不使用、请求或保存学习通账号密码。
- 二维码 5 分钟失效；学习通会话最多保留 24 小时。
- 禁止访问非学习通白名单域名、私网地址和非 HTTPS 地址。
- 单文档上限 100 MB；ZIP 解压总量上限 1 GB、最多 1,000 个文件。
- 现有工作空间配额保持 500 MB 和 500 份资料。
- 视频不下载，只生成课程级“视频资料链接”笔记。
- 所有连接、预览和任务查询必须同时匹配当前 `workspace_id` 与 `user_id`。
- 任何 API、日志和审计记录不得泄露 Cookie、二维码底层凭证或带签名下载地址。
- 功能开关 `LEARNFLOW_CHAOXING_ENABLED` 默认关闭；开关关闭时 API 返回 503 `connector_disabled`。
- 学习通页面改版、验证码和二次验证必须失败关闭，不绕过上游风控。

---

### Task 1: Connector Domain and Encrypted Store

**Files:**
- Create: `backend/app/learning_domain.py`
- Create: `backend/app/learning_store.py`
- Create: `backend/tests/test_learning_store.py`
- Modify: `backend/pyproject.toml`

**Interfaces:**
- Consumes: `utc_now() -> str` from `backend/app/domain.py`.
- Produces: `LearningStore(db_path: Path, connector_key: bytes | None)`, `LearningStore.initialize()`, `save_connection(...)`, `load_connection(...)`, `revoke_connection(...)`, `create_preview(...)`, `get_preview(...)`, `create_job(...)`, `get_job(...)`, `list_job_items(...)`, `update_job_item(...)`.
- Produces: `LearningConnection`, `ImportPreview`, `PreviewCourse`, `PreviewFile`, `ImportJob`, `ImportJobItem` Pydantic models.

- [ ] **Step 1: Add the encryption dependency and write failing store tests**

Add `"cryptography>=45,<47"` to `backend/pyproject.toml`.

```python
def test_connection_session_is_encrypted_and_scoped(tmp_path):
    key = b"x" * 32
    store = LearningStore(tmp_path / "learning.sqlite3", connector_key=key)
    store.initialize()
    store.save_connection(
        workspace_id="w1",
        user_id="u1",
        remote_nickname="同学",
        cookies={"auth": "secret-cookie"},
        expires_at="2099-01-01T00:00:00+00:00",
    )

    assert store.load_connection("w1", "u1").cookies["auth"] == "secret-cookie"
    assert store.load_connection("w2", "u1") is None
    assert "secret-cookie" not in (tmp_path / "learning.sqlite3").read_bytes().decode(
        "utf-8", errors="ignore"
    )
    store.revoke_connection("w1", "u1")
    assert store.load_connection("w1", "u1") is None
```

- [ ] **Step 2: Run the failing test**

Run: `cd backend && uv run pytest tests/test_learning_store.py::test_connection_session_is_encrypted_and_scoped -q`

Expected: FAIL because `app.learning_store` does not exist.

- [ ] **Step 3: Implement domain and store**

Define the public models in `learning_domain.py`:

```python
type ConnectionStatus = Literal["pending", "connected", "expired", "error", "revoked"]
type JobStatus = Literal[
    "queued", "reading", "downloading", "parsing", "completed",
    "partial_failed", "cancelled", "session_expired",
]

class PreviewFile(CamelModel):
    id: str
    name: str
    extension: str
    size_bytes: int = 0
    download_url: str
    supported: bool
    excluded_reason: str | None = None

class PreviewCourse(CamelModel):
    id: str
    title: str
    teacher: str = ""
    documents: list[PreviewFile] = Field(default_factory=list)
    video_links: list[str] = Field(default_factory=list)
```

Implement `LearningStore` with these tables:

```sql
CREATE TABLE learning_connections (
  workspace_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  provider TEXT NOT NULL DEFAULT 'chaoxing',
  remote_nickname TEXT,
  account_fingerprint TEXT,
  session_nonce BLOB,
  session_ciphertext BLOB,
  key_version INTEGER NOT NULL DEFAULT 1,
  expires_at TEXT NOT NULL,
  last_synced_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (workspace_id, user_id, provider)
);
CREATE TABLE learning_previews (...);
CREATE TABLE learning_preview_courses (...);
CREATE TABLE learning_preview_files (...);
CREATE TABLE learning_import_jobs (...);
CREATE TABLE learning_import_items (...);
```

Use AES-256-GCM:

```python
nonce = os.urandom(12)
ciphertext = AESGCM(self.connector_key).encrypt(
    nonce, json.dumps(cookies, ensure_ascii=False).encode(), None
)
```

`load_connection` returns `cookies=None` when expired or when `connector_key` is missing. Every SQL query includes both workspace and user ID.

- [ ] **Step 4: Add scoping and tamper tests**

```python
def test_tampered_ciphertext_fails_closed(tmp_path):
    store = LearningStore(tmp_path / "learning.sqlite3", connector_key=b"k" * 32)
    store.initialize()
    store.save_connection(
        workspace_id="w1", user_id="u1", remote_nickname=None,
        cookies={"auth": "secret"},
        expires_at="2099-01-01T00:00:00+00:00",
    )
    store.connection.execute(
        "UPDATE learning_connections SET session_ciphertext = x'00'"
    )
    assert store.load_connection("w1", "u1").status == "error"
```

- [ ] **Step 5: Run the complete store tests and commit**

Run: `cd backend && uv run pytest tests/test_learning_store.py -q`

Expected: PASS.

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/learning_domain.py \
  backend/app/learning_store.py backend/tests/test_learning_store.py
git commit -m "feat: add encrypted learning connector store"
```

---

### Task 2: Chaoxing QR Login Adapter

**Files:**
- Create: `backend/app/chaoxing_adapter.py`
- Create: `backend/tests/test_chaoxing_adapter.py`

**Interfaces:**
- Consumes: allowlist helper `validate_chaoxing_url(url: str) -> httpx.URL`.
- Produces: `QrTicket` dataclass with `login_id`, `qr_png`, `expires_at`, `poll()`.
- Produces: `ChaoxingAdapter.start_login() -> QrTicket`, `ChaoxingAdapter.catalog(cookies) -> list[PreviewCourse]`, `ChaoxingAdapter.download(cookies, file, destination) -> str`.

- [ ] **Step 1: Write fake-upstream login tests**

```python
@pytest.mark.asyncio
async def test_qr_login_polls_to_connected_state():
    adapter = FakeChaoxingAdapter()
    ticket = adapter.start_login()
    assert ticket.qr_png.startswith(b"\x89PNG")
    first = ticket.poll()
    assert first.status == "pending"
    adapter.confirm_login(ticket.login_id)
    finished = ticket.poll()
    assert finished.status == "connected"
    assert finished.cookies["auth"] == "session-token"
```

- [ ] **Step 2: Run it and verify failure**

Run: `cd backend && uv run pytest tests/test_chaoxing_adapter.py -q`

Expected: FAIL because the adapter module does not exist.

- [ ] **Step 3: Implement the HTTP QR flow**

Use these production endpoints:

```python
LOGIN_URL = "https://passport2.chaoxing.com/login?fid=&refer=http%3A%2F%2Fi.mooc.chaoxing.com%2Fspace%2Findex"
COURSE_API = "https://mooc1-api.chaoxing.com/mycourse/backclazzdata?view=json&rss=1"
```

Parse `#uuid`, `#enc`, and `/createqr?...` from the login HTML. Proxy the QR image with the same `httpx.Client`. Poll:

```python
response = client.post(
    "https://passport2.chaoxing.com/getauthstatus/v2",
    data={
        "enc": enc,
        "uuid": uuid,
        "doubleFactorLogin": "0",
        "forbidotherlogin": "0",
    },
)
```

Map upstream responses to `pending`, `confirming`, `connected`, `cancelled`, `expired`, and `verification_required`. Never return cookies to the browser.

- [ ] **Step 4: Implement catalog normalization**

Parse teacher courses from all supported JSON shapes and fall back to course-card anchors:

```python
def normalize_course_payload(payload: dict) -> list[PreviewCourse]:
    cards: list[dict] = []
    for channel in payload.get("channelList", []):
        data = channel.get("content", {}).get("course", {}).get("data", [])
        if isinstance(data, list):
            cards.extend(item for item in data if isinstance(item, dict))
    return [course_from_card(card) for card in cards if card.get("name")]
```

Course and file URLs must pass `validate_chaoxing_url`. Tests provide JSON fixtures for normal, empty, changed-page and private-IP cases.

- [ ] **Step 5: Add redirect, timeout, size and MIME tests**

```python
def test_private_redirect_is_rejected(fake_server):
    with pytest.raises(ValueError, match="upstream_host_not_allowed"):
        validate_chaoxing_url("http://127.0.0.1/private.pdf")

def test_oversize_download_is_deleted(tmp_path):
    with pytest.raises(ValueError, match="file_too_large"):
        adapter.download({}, PreviewFile(size_bytes=101 * 1024 * 1024), tmp_path / "a.pdf")
    assert not (tmp_path / "a.pdf").exists()
```

- [ ] **Step 6: Run tests and commit**

Run: `cd backend && uv run pytest tests/test_chaoxing_adapter.py -q`

Expected: PASS.

```bash
git add backend/app/chaoxing_adapter.py backend/tests/test_chaoxing_adapter.py
git commit -m "feat: add Chaoxing QR login adapter"
```

---

### Task 3: Preview, Folder Mapping and Import Jobs

**Files:**
- Create: `backend/app/learning_service.py`
- Create: `backend/tests/test_learning_service.py`
- Modify: `backend/app/learning_store.py`

**Interfaces:**
- Consumes: `LearningStore`, `ChaoxingAdapter`, `KnowledgeStore`.
- Produces: `LearningService.create_preview(workspace_id, user_id) -> ImportPreview`.
- Produces: `LearningService.create_import(workspace_id, user_id, preview_id, mappings) -> ImportJob`.
- Produces: `LearningService.retry_failed(job_id, workspace_id, user_id) -> ImportJob`.

- [ ] **Step 1: Write preview and mapping tests**

```python
def test_preview_marks_unsupported_files(service):
    preview = service.create_preview("w1", "u1")
    assert preview.total_documents == 2
    assert preview.courses[0].documents[1].excluded_reason == "unsupported_file_type"

def test_mapping_rejects_foreign_course(service):
    with pytest.raises(ValueError, match="course_not_found"):
        service.create_import(
            "w1", "u1", "preview-1",
            [{"previewCourseId": "c1", "targetCourseId": "foreign"}],
        )
```

- [ ] **Step 2: Run tests and verify failure**

Run: `cd backend && uv run pytest tests/test_learning_service.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement preview generation**

Normalize each course and file, select `new`, `merge` or `skip`, calculate quota:

```python
supported = Path(file.name).suffix.casefold() in SUPPORTED_EXTENSIONS
excluded_reason = None if supported else "unsupported_file_type"
if file.size_bytes > MAX_IMPORT_FILE_BYTES:
    excluded_reason = "file_too_large"
```

Preview expires after 30 minutes. Persist only normalized metadata and opaque preview IDs.

- [ ] **Step 4: Implement import-job creation transactionally**

For each selected preview course:

- `new`: create a new `KnowledgeStore` folder.
- `merge`: verify target folder belongs to workspace.
- `skip`: omit course and files.

Create one job and one item per supported file plus one video-links item per course. Store no cookies in job rows.

- [ ] **Step 5: Test cancel and retry state transitions**

```python
def test_cancelled_job_cannot_restart(service, job):
    service.cancel_job(job.id, "w1", "u1")
    with pytest.raises(ValueError, match="invalid_job_state"):
        service.retry_failed(job.id, "w1", "u1")
```

- [ ] **Step 6: Run and commit**

Run: `cd backend && uv run pytest tests/test_learning_service.py tests/test_learning_store.py -q`

Expected: PASS.

```bash
git add backend/app/learning_service.py backend/app/learning_store.py \
  backend/tests/test_learning_service.py
git commit -m "feat: add learning import preview and jobs"
```

---

### Task 4: Persistent Import Worker and Knowledge Upsert

**Files:**
- Create: `backend/app/learning_worker.py`
- Create: `backend/tests/test_learning_worker.py`
- Modify: `backend/app/knowledge_store.py`
- Modify: `backend/app/knowledge_domain.py`
- Modify: `backend/tests/test_knowledge_store.py`

**Interfaces:**
- Produces: `KnowledgeStore.upsert_external_asset(...) -> tuple[KnowledgeAsset, bool]` where bool means created.
- Produces: `KnowledgeStore.upsert_external_note(...) -> KnowledgeAsset`.
- Produces: `LearningWorker.start()`, `LearningWorker.stop()`, `LearningWorker.wake(job_id)`.

- [ ] **Step 1: Write external upsert and dedupe tests**

```python
def test_external_asset_skips_unchanged_and_updates_changed(store, course):
    first, created = store.upsert_external_asset(
        course_id=course.id, workspace_id="w1", external_source="chaoxing",
        external_id="file-1", checksum="aaa", title="讲义",
        original_name="讲义.pdf", mime_type="application/pdf",
        file_relpath="w1/a.pdf", extraction=TextExtraction("第一版", "ready"),
        tags=["学习通"], size_bytes=10,
    )
    assert created is True
    same, created = store.upsert_external_asset(
        course_id=course.id, workspace_id="w1", external_source="chaoxing",
        external_id="file-1", checksum="aaa", title="讲义",
        original_name="讲义.pdf", mime_type="application/pdf",
        file_relpath="w1/a.pdf", extraction=TextExtraction("第一版", "ready"),
        tags=["学习通"], size_bytes=10,
    )
    assert same.id == first.id and created is False
```

- [ ] **Step 2: Run the failing test**

Run: `cd backend && uv run pytest tests/test_knowledge_store.py -q`

Expected: FAIL because `upsert_external_asset` is missing.

- [ ] **Step 3: Add provenance columns and transactional upsert**

Add:

```sql
ALTER TABLE knowledge_assets ADD COLUMN external_source TEXT;
ALTER TABLE knowledge_assets ADD COLUMN external_id TEXT;
ALTER TABLE knowledge_assets ADD COLUMN source_url TEXT;
ALTER TABLE knowledge_assets ADD COLUMN checksum TEXT;
```

Use `_ensure_column` for migration. Deduplicate by `(workspace_id, external_source, external_id)`. On unchanged checksum, return existing without copying. On changed checksum, update existing metadata, delete old chunks, insert new chunks, replace file path, and remove the old file only after commit.

- [ ] **Step 4: Write worker progress, partial failure and restart tests**

```python
def test_worker_marks_partial_failure_and_retries_only_failed(worker, job):
    worker.run_once()
    result = worker.store.get_job(job.id, "w1", "u1")
    assert result.status == "partial_failed"
    assert result.completed_items == 2
    assert result.failed_items == 1
    worker.retry_failed(job.id, "w1", "u1")
    worker.run_once()
    assert worker.store.get_job(job.id, "w1", "u1").status == "completed"
```

- [ ] **Step 5: Implement worker with bounded concurrency**

Use a thread-safe queue, at most two file downloads, retry only `failed`, update progress after every item, and recover `queued`/interrupted jobs at startup. Download to `uploads/tmp/{workspace_id}/{job_id}/`, validate content using `inspect_uploaded_file`, extract with `extract_text`, then atomically move to final upload path.

Cancellation is checked between items and before commit. Expired sessions set the job to `session_expired`; temporary files are always removed in `finally`.

- [ ] **Step 6: Run worker and knowledge tests and commit**

Run: `cd backend && uv run pytest tests/test_learning_worker.py tests/test_knowledge_store.py -q`

Expected: PASS.

```bash
git add backend/app/learning_worker.py backend/app/knowledge_store.py \
  backend/app/knowledge_domain.py backend/tests/test_learning_worker.py \
  backend/tests/test_knowledge_store.py
git commit -m "feat: run persistent learning imports"
```

---

### Task 5: Authenticated Learning API and Configuration

**Files:**
- Create: `backend/app/learning_api.py`
- Create: `backend/tests/test_learning_api.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/main.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `LearningService`, `LearningStore`, `AuthManager`.
- Produces: every endpoint listed in the design spec.
- Produces: config fields `chaoxing_enabled: bool`, `connector_key: str | None`.

- [ ] **Step 1: Write auth, feature flag and isolation API tests**

```python
@pytest.mark.asyncio
async def test_learning_api_is_private(client):
    response = await client.get("/api/learning/chaoxing/status")
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_connector_disabled_fails_closed(client, auth_headers):
    response = await client.post(
        "/api/learning/chaoxing/login", headers=auth_headers
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "connector_disabled"
```

- [ ] **Step 2: Run and verify failure**

Run: `cd backend && uv run pytest tests/test_learning_api.py -q`

Expected: FAIL because routes are absent.

- [ ] **Step 3: Implement routes**

Register the router with `build_learning_router(service, auth_manager, settings)`. Every route depends on `auth_manager.require_auth`. Status and QR responses must not contain cookies. QR image returns `Response(content=qr_png, media_type="image/png")`.

Use stable exception mapping:

```python
ERROR_STATUS = {
    "connector_disabled": 503,
    "login_not_found": 404,
    "login_expired": 410,
    "session_expired": 401,
    "quota_exceeded": 413,
    "file_too_large": 413,
    "invalid_file_content": 422,
    "source_permission_denied": 403,
    "verification_required": 409,
}
```

Limit login start and preview generation to five requests per user per hour.

- [ ] **Step 4: Wire app startup and shutdown**

Create:

```python
settings = load_settings()
connector_key = decode_connector_key(settings.connector_key)
learning_store = LearningStore(runtime_dir / "learnflow.sqlite3", connector_key)
learning_store.initialize()
learning_service = LearningService(
    learning_store,
    ChaoxingAdapter(enabled=settings.chaoxing_enabled),
    knowledge_store,
)
learning_worker = LearningWorker(learning_service)
app.state.learning_service = learning_service
app.state.learning_worker = learning_worker
```

Start the worker in FastAPI lifespan and stop it on shutdown.

- [ ] **Step 5: Verify API regression and commit**

Run: `cd backend && uv run pytest tests/test_learning_api.py tests/test_auth.py -q`

Expected: PASS.

```bash
git add backend/app/learning_api.py backend/app/config.py backend/app/main.py \
  backend/tests/test_learning_api.py .env.example
git commit -m "feat: expose authenticated learning connector API"
```

---

### Task 6: Frontend Learning Connector Wizard

**Files:**
- Create: `frontend/src/components/LearningConnectorDialog.tsx`
- Create: `frontend/tests/learning-connector.test.tsx`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/pages/CoursesPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: connector API types and endpoints.
- Produces: `LearningConnectorDialog({ open, courses, onClose, onImported })`.
- Produces: `learningConnectorApi.startLogin()`, `pollLogin()`, `qrUrl()`, `status()`, `createPreview()`, `createImport()`, `getJob()`, `cancel()`, `retry()`, `disconnect()`.

- [ ] **Step 1: Write component tests for required feedback**

```tsx
it("moves from QR to preview and creates an import", async () => {
  render(<LearningConnectorDialog open courses={[]} onClose={vi.fn()} onImported={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: "生成学习通二维码" }));
  expect(await screen.findByAltText("学习通扫码登录二维码")).toBeInTheDocument();
  act(() => vi.advanceTimersByTime(3000));
  expect(await screen.findByText("选择要导入的课程")).toBeInTheDocument();
  await user.click(screen.getByRole("checkbox", { name: /高等数学/ }));
  await user.click(screen.getByRole("button", { name: "确认导入" }));
  expect(await screen.findByText("同步任务已启动")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test and verify failure**

Run: `cd frontend && npm test -- --run tests/learning-connector.test.tsx`

Expected: FAIL because component does not exist.

- [ ] **Step 3: Implement the shared API and TypeScript types**

Add exact camelCase types for connection, QR login, preview course, preview file, folder mapping and job progress. Use existing `request()` and `emptyRequest()` so 401 events remain consistent. QR image URL includes cache-busting `revision`.

- [ ] **Step 4: Implement the wizard**

Use four explicit steps: `connection`, `preview`, `mapping`, `progress/result`. Every async button gets a disabled state, spinner and stable success/error message. Poll login every 2 seconds for 5 minutes and job every 1.5 seconds while visible, backing off to 10 seconds when `document.hidden`.

Expose “刷新二维码”, “取消连接”, “重新加载课程”, “全选文档”, “取消全选”, “重试失败项”, “取消同步” and “打开已导入文件夹”. None of these buttons may resolve silently.

- [ ] **Step 5: Integrate entry points**

Add “连接学习通” and “从学习通导入” to `CoursesPage`. On completion call `onImported()` to reload overview and courses. Add a mobile-safe bottom-sheet CSS layout and focus trap.

- [ ] **Step 6: Run frontend tests and build and commit**

Run: `cd frontend && npm test -- --run && npm run build`

Expected: PASS with no TypeScript errors.

```bash
git add frontend/src/components/LearningConnectorDialog.tsx \
  frontend/src/types.ts frontend/src/api.ts frontend/src/pages/CoursesPage.tsx \
  frontend/src/App.tsx frontend/src/styles.css \
  frontend/tests/learning-connector.test.tsx
git commit -m "feat: add learning connector import wizard"
```

---

### Task 7: Safe ZIP Fallback

**Files:**
- Create: `backend/app/zip_import.py`
- Create: `backend/tests/test_zip_import.py`
- Modify: `backend/app/learning_api.py`
- Modify: `frontend/src/components/LearningConnectorDialog.tsx`

**Interfaces:**
- Produces: `inspect_zip(path: Path) -> ImportPreview`.
- Produces: `POST /api/learning/imports/zip/previews` accepting multipart field `file`.

- [ ] **Step 1: Write unsafe archive tests**

```python
@pytest.mark.parametrize("name", ["../escape.pdf", "/absolute.pdf", "a/../../b.pdf"])
def test_zip_path_traversal_is_rejected(tmp_path, name):
    archive = tmp_path / "unsafe.zip"
    with ZipFile(archive, "w") as zf:
        zf.writestr(name, b"%PDF-1.4")
    with pytest.raises(ValueError, match="invalid_zip_member"):
        inspect_zip(archive)
```

- [ ] **Step 2: Run failing tests**

Run: `cd backend && uv run pytest tests/test_zip_import.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement secure inspection**

Reject absolute paths, `..`, backslashes, symlinks, encrypted members, nested ZIPs, more than 1,000 members and more than 1 GB total uncompressed size. Create one preview course per top-level folder; root-level documents go to a course named after the archive.

- [ ] **Step 4: Add multipart API and UI upload states**

Limit ZIP upload to 250 MB. Show selected filename, upload progress state, preview, errors and a retry action. Never silently accept archives with excluded members; show counts and reasons.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && uv run pytest tests/test_zip_import.py tests/test_learning_api.py -q`

Expected: PASS.

```bash
git add backend/app/zip_import.py backend/tests/test_zip_import.py \
  backend/app/learning_api.py frontend/src/components/LearningConnectorDialog.tsx
git commit -m "feat: add safe ZIP fallback import"
```

---

### Task 8: End-to-End Verification, Documentation and Deployment

**Files:**
- Modify: `frontend/tests/e2e/app.spec.ts`
- Modify: `docs/competition/requirements.md`
- Modify: `docs/competition/architecture.md`
- Modify: `docs/competition/security.md`
- Modify: `docs/competition/third-party-licenses.md`
- Modify: `docs/competition/test-report.md`
- Modify: `deploy/README.md`
- Modify: `deploy/remote-install.sh`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: documented production env, CI-tested feature and release checklist.

- [ ] **Step 1: Add Playwright desktop and mobile connector flows**

Use `page.route()` to fake connector APIs. Assert:

```ts
await expect(page.getByText("邀请学习通扫码授权")).toBeVisible();
await page.getByRole("button", { name: "生成学习通二维码" }).click();
await expect(page.getByAltText("学习通扫码登录二维码")).toBeVisible();
await expect(page.getByText("选择要导入的课程")).toBeVisible();
await page.getByRole("checkbox", { name: /高等数学/ }).check();
await page.getByRole("button", { name: "确认导入" }).click();
await expect(page.getByText("导入完成")).toBeVisible();
```

Repeat at `390 × 844` and verify no horizontal overflow.

- [ ] **Step 2: Update documentation**

Document:

- connector scope and QR-only authorization;
- 5-minute QR and 24-hour session;
- document-only policy and video links;
- `LEARNFLOW_CHAOXING_ENABLED=false|true`;
- connector key generation: `openssl rand -base64 32`;
- ZIP fallback;
- real-account acceptance test and disconnect procedure;
- upstream API change/risk and rollback with the feature flag.

- [ ] **Step 3: Run complete verification**

Run:

```bash
cd backend && uv run pytest -q
cd backend && uvx ruff check app tests
cd frontend && npm test -- --run
cd frontend && npm run build
cd frontend && npm run test:e2e
```

Expected: every command exits 0.

- [ ] **Step 4: Verify no secret leakage**

Run:

```bash
rg -n "Cookie:|cookies=|auth=.*session|LEARNFLOW_CONNECTOR_KEY=" \
  backend frontend docs deploy .env.example \
  -g '!frontend/node_modules/**' -g '!backend/.venv/**' \
  -g '!frontend/dist/**'
```

Expected: only safe configuration names and redacted tests, never a real credential.

- [ ] **Step 5: Commit documentation and CI**

```bash
git add frontend/tests/e2e/app.spec.ts docs/competition deploy
git commit -m "docs: document learning connector operations"
```

- [ ] **Step 6: Deploy behind the disabled feature flag**

Deploy with `LEARNFLOW_CHAOXING_ENABLED=false`, configure the encryption key out of band, run public readiness and regression checks, then enable the feature only for the owner account. Do not create a test learning通 account.
