# Personal Knowledge Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将知序改造成以个人课程资料、笔记和知识片段为中心的知识管理工作台，并保留现有学习智能体能力。

**Architecture:** 后端新增独立的 knowledge domain、ingestion、store 和 API 模块，继续复用现有 SQLite 数据库与 FastAPI；前端新增知识首页、课程空间、知识库、资料详情和全局采集面板，现有画像与智能体页面继续保留。

**Tech Stack:** FastAPI、Pydantic、SQLite、pypdf、python-docx、python-pptx、Pillow、pytesseract、React 19、TypeScript、Vitest、Testing Library、Playwright。

## Global Constraints

- 本阶段固定单用户工作空间 `workspace_id = "default"`。
- 文件大小上限为 25 MB。
- 允许扩展名为 `.pdf`、`.docx`、`.pptx`、`.md`、`.txt`、`.png`、`.jpg`、`.jpeg`、`.webp`。
- 不上传文件到第三方服务，不进行学习通账号代登录。
- 原始文件保存在 `LEARNFLOW_DATA_DIR/uploads/`，不得保存绝对路径到数据库。
- 所有用户可见异步操作必须有加载、成功、失败或不可用状态。
- 删除课程和资料必须先确认。
- 现有画像、资源生成、路径、辅导和评估测试不得回归。
- 手机端固定底部导航；桌面端使用侧边栏。

---

### Task 1: Knowledge Domain Models

**Files:**
- Create: `backend/app/knowledge_domain.py`
- Test: `backend/tests/test_knowledge_models.py`

**Interfaces:**
- Produces: `Course`, `CourseCreate`, `CourseUpdate`, `KnowledgeAsset`, `KnowledgeChunk`, `KnowledgeOverview`, `CourseSummary`.
- Produces: `normalize_tags(values: list[str]) -> list[str]`.
- Produces: `excerpt(text: str, limit: int = 180) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
from app.knowledge_domain import CourseCreate, normalize_tags, excerpt


def test_course_create_trims_title_and_rejects_empty():
    course = CourseCreate(title="  数据结构  ", description="  链表、树、图  ")
    assert course.title == "数据结构"

    try:
        CourseCreate(title="   ")
    except ValueError:
        pass
    else:
        raise AssertionError("empty title must fail")


def test_tags_are_trimmed_deduplicated_and_limited():
    assert normalize_tags([" AI ", "ai", "", "图论", "图论"]) == ["AI", "图论"]


def test_excerpt_collapses_whitespace_and_limits_length():
    assert excerpt("  第一行\n\n第二行  ", 5) == "第一行 第"
```

- [ ] **Step 2: Verify failure**

Run: `cd backend && uv run pytest tests/test_knowledge_models.py -q`

Expected: FAIL because `app.knowledge_domain` does not exist.

- [ ] **Step 3: Implement models and helpers**

```python
from pydantic import BaseModel, Field, field_validator


def normalize_tags(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        tag = value.strip()
        key = tag.casefold()
        if tag and key not in seen:
            seen.add(key)
            result.append(tag)
    return result[:12]


def excerpt(text: str, limit: int = 180) -> str:
    compact = " ".join(text.split())
    return compact[:limit]


class CourseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    color: str = Field(default="#e25d3f", pattern=r"^#[0-9a-fA-F]{6}$")

    @field_validator("title", "description")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()
```

Define frozen `KnowledgeAsset`, `KnowledgeChunk`, `CourseSummary`, `KnowledgeOverview`, `CourseUpdate`, `NoteCreate`, and `AssetDetail` models with the fields from the design spec.

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_knowledge_models.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/knowledge_domain.py backend/tests/test_knowledge_models.py
git commit -m "feat: add personal knowledge domain models"
```

---

### Task 2: Text Extraction and Knowledge Building

**Files:**
- Create: `backend/app/ingestion.py`
- Modify: `backend/pyproject.toml`
- Test: `backend/tests/test_ingestion.py`

**Interfaces:**
- Produces: `SUPPORTED_EXTENSIONS`, `MAX_UPLOAD_BYTES`.
- Produces: `validate_upload(filename: str, size: int) -> str`.
- Produces: `extract_text(path: Path, mime_type: str | None) -> TextExtraction`.
- Produces: `build_knowledge(text: str, title: str, tags: list[str]) -> list[KnowledgeChunkDraft]`.

- [ ] **Step 1: Write failing extraction tests**

```python
from pathlib import Path
import pytest
from app.ingestion import build_knowledge, extract_text, validate_upload


def test_markdown_text_is_extracted_and_chunked(tmp_path):
    path = tmp_path / "lesson.md"
    path.write_text("# 图论\n\n广度优先搜索使用队列。\n\n深度优先搜索使用栈。", encoding="utf-8")
    result = extract_text(path, "text/markdown")
    assert result.text.startswith("# 图论")
    chunks = build_knowledge(result.text, "图论笔记", ["搜索"])
    assert chunks
    assert "广度优先搜索" in chunks[0].excerpt


def test_unsupported_extension_is_rejected():
    with pytest.raises(ValueError, match="unsupported_file_type"):
        validate_upload("video.mp4", 10)


def test_oversized_upload_is_rejected():
    with pytest.raises(ValueError, match="file_too_large"):
        validate_upload("notes.md", 26 * 1024 * 1024)
```

- [ ] **Step 2: Verify failure**

Run: `cd backend && uv run pytest tests/test_ingestion.py -q`

Expected: FAIL because module and functions are missing.

- [ ] **Step 3: Add parser dependencies**

Update `backend/pyproject.toml`:

```toml
dependencies = [
  "fastapi>=0.115,<1",
  "uvicorn[standard]>=0.34,<1",
  "pydantic>=2.10,<3",
  "httpx>=0.28,<1",
  "python-multipart>=0.0.20,<1",
  "pypdf>=5.0,<7",
  "python-docx>=1.1,<2",
  "python-pptx>=1.0,<2",
  "pillow>=11.0,<13",
  "pytesseract>=0.3.13,<1",
]
```

- [ ] **Step 4: Implement extraction**

```python
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".md", ".txt", ".png", ".jpg", ".jpeg", ".webp"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def validate_upload(filename: str, size: int) -> str:
    suffix = Path(filename).suffix.casefold()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError("unsupported_file_type")
    if size <= 0:
        raise ValueError("empty_file")
    if size > MAX_UPLOAD_BYTES:
        raise ValueError("file_too_large")
    return suffix
```

Implement text, PDF, DOCX, PPTX, image OCR, and unavailable-OCR branches. `build_knowledge` splits normalized paragraphs into chunks of at most 700 characters and returns drafts with a title, excerpt, and normalized tags.

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/test_ingestion.py -q`

Expected: PASS. OCR failure path must return `ready_image_only`, not raise.

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/ingestion.py backend/tests/test_ingestion.py
git commit -m "feat: add personal material ingestion"
```

---

### Task 3: Knowledge Repository and Seed Course

**Files:**
- Create: `backend/app/knowledge_store.py`
- Modify: `backend/app/repository.py`
- Test: `backend/tests/test_knowledge_store.py`

**Interfaces:**
- Consumes: domain models and `build_knowledge`.
- Produces: `KnowledgeStore.initialize()`, `create_course`, `list_courses`, `get_course`, `update_course`, `delete_course`.
- Produces: `create_asset`, `list_assets`, `get_asset`, `delete_asset`, `search`, `overview`.

- [ ] **Step 1: Write failing store tests**

```python
from app.knowledge_domain import CourseCreate, NoteCreate
from app.knowledge_store import KnowledgeStore


def test_course_note_and_search_round_trip(tmp_path):
    store = KnowledgeStore(tmp_path / "learnflow.sqlite3", tmp_path / "uploads")
    store.initialize()
    course = store.create_course(CourseCreate(title="数据结构", description="树与图"))
    asset = store.create_note(course.id, NoteCreate(title="BFS", content="广度优先搜索使用队列", tags=["图论"]))

    assert store.get_asset(asset.id).title == "BFS"
    results = store.search("队列")
    assert results[0].asset_id == asset.id


def test_delete_course_removes_assets_and_chunks(tmp_path):
    store = KnowledgeStore(tmp_path / "learnflow.sqlite3", tmp_path / "uploads")
    store.initialize()
    course = store.create_course(CourseCreate(title="操作系统"))
    store.create_note(course.id, NoteCreate(title="进程", content="进程是资源分配单位"))

    store.delete_course(course.id)

    assert store.get_course(course.id) is None
    assert store.search("资源分配") == []
```

- [ ] **Step 2: Verify failure**

Run: `cd backend && uv run pytest tests/test_knowledge_store.py -q`

Expected: FAIL because `KnowledgeStore` does not exist.

- [ ] **Step 3: Create tables**

Add `courses`, `knowledge_assets`, and `knowledge_chunks` tables with foreign keys and indexes on `course_id`, `asset_id`, `created_at`, and `tag_json`.

Use these database columns:

```text
courses:
  id, workspace_id, title, description, color, created_at, updated_at

knowledge_assets:
  id, workspace_id, course_id, kind, title, original_name, mime_type,
  file_relpath, status, content, summary, tags_json, error,
  created_at, updated_at

knowledge_chunks:
  id, asset_id, course_id, title, excerpt, search_text, tags_json, created_at
```

- [ ] **Step 4: Implement store behavior**

`create_note` uses `build_knowledge` and inserts chunks in the same transaction. `search` normalizes the query, filters courses/titles/content/tags/chunks, and returns deduplicated `KnowledgeChunk` records. `overview` returns counts, recent assets, courses, and tags; `pendingCount` counts `processing` and `failed` assets. When the courses table is empty, seed the default `人工智能导论` course and import the five existing Markdown files under `backend/data/knowledge/ai_intro/` as example assets with chunks; repeated startup must not duplicate them.

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/test_knowledge_store.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/knowledge_store.py backend/app/repository.py backend/tests/test_knowledge_store.py
git commit -m "feat: persist personal courses and knowledge chunks"
```

---

### Task 4: Knowledge API and Uploads

**Files:**
- Create: `backend/app/knowledge_api.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api.py`
- Test: `backend/tests/test_knowledge_api.py`
- Modify: `deploy/remote-install.sh`

**Interfaces:**
- Consumes: `KnowledgeStore`, `validate_upload`, `extract_text`.
- Produces: functions from the design spec under `/api/knowledge`, `/api/courses`, and `/api/assets`.

- [ ] **Step 1: Write failing API tests**

```python
import httpx
import pytest
from app.main import create_app


@pytest.mark.asyncio
async def test_create_course_upload_markdown_and_search(tmp_path):
    app = create_app(data_dir=tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        course = (await client.post("/api/courses", json={"title": "算法", "description": "搜索与图"})).json()
        upload = await client.post(
            f"/api/courses/{course['id']}/assets",
            files={"file": ("bfs.md", "# BFS\n\n广度优先搜索使用队列。".encode(), "text/markdown")},
            data={"title": "BFS 课堂笔记", "tags": "图论,搜索"},
        )
        assert upload.status_code == 201
        assert upload.json()["knowledgeCount"] >= 1
        search = (await client.get("/api/knowledge/search", params={"q": "队列"})).json()
        assert search["items"][0]["courseTitle"] == "算法"
```

- [ ] **Step 2: Verify failure**

Run: `cd backend && uv run pytest tests/test_knowledge_api.py -q`

Expected: FAIL with 404 for `/api/courses`.

- [ ] **Step 3: Implement API**

- Create the router with multipart upload.
- Read the upload in bounded chunks and reject when accumulated size exceeds `MAX_UPLOAD_BYTES`.
- Save with a UUID filename under `uploads/<course_id>/`.
- Run `extract_text` and `build_knowledge`; persist the asset and chunks.
- Return `201` for uploads and notes, `204` for deletes.
- Reject invalid IDs with `404`, invalid files with `422`, and avoid exposing filesystem paths.
- Add `python-multipart`, PDF/DOCX/PPTX/OCR dependencies, `tesseract-ocr`, and `tesseract-ocr-chi-sim` to deployment.

- [ ] **Step 4: Run API tests**

Run: `cd backend && uv run pytest tests/test_knowledge_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/knowledge_api.py backend/app/main.py backend/app/api.py backend/tests/test_knowledge_api.py deploy/remote-install.sh
git commit -m "feat: expose personal knowledge APIs"
```

---

### Task 5: Frontend Knowledge Types and API Client

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`
- Create: `frontend/tests/knowledge-api.test.ts`

**Interfaces:**
- Produces: `Course`, `KnowledgeAsset`, `KnowledgeChunk`, `AssetDetail`, `KnowledgeOverview`.
- Produces: `knowledgeApi.overview`, `listCourses`, `createCourse`, `updateCourse`, `deleteCourse`, `listAssets`, `uploadAsset`, `createNote`, `getAsset`, `deleteAsset`, `search`.

- [ ] **Step 1: Write failing upload contract test**

```ts
test("upload sends multipart data without forcing JSON content type", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ id: "a1", title: "笔记" }), {
      status: 201,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  await knowledgeApi.uploadAsset("c1", new File(["正文"], "note.md", { type: "text/markdown" }));
  const init = fetchMock.mock.calls[0][1] as RequestInit;
  expect(init.body).toBeInstanceOf(FormData);
  expect(new Headers(init.headers).has("Content-Type")).toBe(false);
});
```

- [ ] **Step 2: Verify failure**

Run: `cd frontend && npm test -- --run tests/knowledge-api.test.ts`

Expected: FAIL because `knowledgeApi` is missing.

- [ ] **Step 3: Implement types and multipart client**

Do not reuse the JSON-only `request()` helper for FormData. Implement `formRequest<T>()` that omits the JSON `Content-Type` and keeps browser-generated multipart boundaries.

- [ ] **Step 4: Run test**

Run: `cd frontend && npm test -- --run tests/knowledge-api.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types.ts frontend/src/api.ts frontend/tests/knowledge-api.test.ts
git commit -m "feat: add personal knowledge frontend API"
```

---

### Task 6: Capture Dialog and Course Management

**Files:**
- Create: `frontend/src/components/CaptureDialog.tsx`
- Create: `frontend/src/pages/CoursesPage.tsx`
- Create: `frontend/src/pages/CourseDetailPage.tsx`
- Create: `frontend/tests/knowledge-components.test.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- `CaptureDialog` consumes `courses`, `initialCourseId`, `onClose`, `onCreated`.
- `CoursesPage` consumes `courses`, `loading`, `error`, `onCreate`, `onOpen`, `onRefresh`.
- `CourseDetailPage` consumes `courseId`, `onBack`, `onCapture`.

- [ ] **Step 1: Write failing component tests**

```tsx
test("capture dialog exposes file, camera and note modes", () => {
  render(<CaptureDialog courses={[course]} onClose={vi.fn()} onCreated={vi.fn()} />);
  expect(screen.getByRole("tab", { name: "上传文件" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "拍照/图片" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "快速笔记" })).toBeInTheDocument();
});

test("course page confirms before deleting a course", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<CoursesPage courses={[course]} loading={false} error={null} onCreate={vi.fn()} onOpen={vi.fn()} onRefresh={vi.fn()} onDelete={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "删除 数据结构" }));
  expect(confirm).toHaveBeenCalled();
});
```

- [ ] **Step 2: Verify failure**

Run: `cd frontend && npm test -- --run tests/knowledge-components.test.tsx`

Expected: FAIL because components do not exist.

- [ ] **Step 3: Implement components**

- Use a modal dialog with three tabs.
- File input: `accept` matching supported extensions.
- Camera input: `accept="image/*" capture="environment"`.
- Note form: title, content, tags.
- Surface upload filename, processing text, success count, OCR-only warning, and retry.
- Course cards show asset count, knowledge count, updated time, open and delete actions.

- [ ] **Step 4: Run tests**

Run: `cd frontend && npm test -- --run tests/knowledge-components.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/CaptureDialog.tsx frontend/src/pages/CoursesPage.tsx frontend/src/pages/CourseDetailPage.tsx frontend/tests/knowledge-components.test.tsx frontend/src/styles.css
git commit -m "feat: add course spaces and capture flow"
```

---

### Task 7: Knowledge Dashboard, Search and Asset Detail

**Files:**
- Create: `frontend/src/pages/KnowledgeDashboardPage.tsx`
- Create: `frontend/src/pages/KnowledgePage.tsx`
- Create: `frontend/src/pages/AssetDetailPage.tsx`
- Create: `frontend/tests/knowledge-pages.test.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Dashboard consumes overview, recent assets, and navigation callbacks.
- Knowledge page consumes query results and tag filters.
- Asset detail consumes `AssetDetail` and source file URL.

- [ ] **Step 1: Write failing page tests**

```tsx
test("empty dashboard asks the user to create a first course", () => {
  render(<KnowledgeDashboardPage overview={{ courseCount: 0, assetCount: 0, knowledgeCount: 0, pendingCount: 0, recentAssets: [], courses: [], topTags: [] }} onCapture={vi.fn()} onOpenCourse={vi.fn()} onOpenKnowledge={vi.fn()} onCreateCourse={vi.fn()} />);
  expect(screen.getByText("创建你的第一门课程")).toBeInTheDocument();
});

test("search result keeps course and asset source", () => {
  render(<KnowledgePage results={[chunk]} loading={false} error={null} query="队列" onQueryChange={vi.fn()} onOpenAsset={vi.fn()} />);
  expect(screen.getByText("算法 · BFS 课堂笔记")).toBeInTheDocument();
  expect(screen.getByText(/广度优先搜索使用队列/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Verify failure**

Run: `cd frontend && npm test -- --run tests/knowledge-pages.test.tsx`

Expected: FAIL because pages do not exist.

- [ ] **Step 3: Implement pages**

- Dashboard: stats, recent assets, course overview, top tags and empty onboarding.
- Knowledge: search box, tag chips, result cards and clear empty state.
- Asset detail: title, course, tags, status, text content, knowledge chunks and original-file action.
- Never render uploaded HTML as active markup.

- [ ] **Step 4: Run tests**

Run: `cd frontend && npm test -- --run tests/knowledge-pages.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/KnowledgeDashboardPage.tsx frontend/src/pages/KnowledgePage.tsx frontend/src/pages/AssetDetailPage.tsx frontend/tests/knowledge-pages.test.tsx frontend/src/styles.css
git commit -m "feat: add personal knowledge dashboard and search"
```

---

### Task 8: App Navigation Integration and Personal Profile Bootstrap

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/pages/HomePage.tsx`
- Modify: `frontend/src/pages/ProfilePage.tsx`
- Modify: `frontend/tests/app.test.tsx`
- Modify: `frontend/tests/e2e/app.spec.ts`

**Interfaces:**
- App navigation adds `courses` and `knowledge`.
- App owns `courses`, `overview`, `activeCourseId`, `activeAssetId`, and `captureOpen`.
- Produces `createPersonalLearner()` calling `POST /api/learners` with no `persona_id`.

- [ ] **Step 1: Write failing tests**

```tsx
test("app opens on knowledge dashboard instead of persona picker", () => {
  render(<App />);
  expect(screen.getByText("个人知识工作台")).toBeInTheDocument();
  expect(screen.queryByText("选择一位演示学生")).not.toBeInTheDocument();
});

test("profile can create a personal learner without a demo persona", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: "l1", name: "我的学习空间", course_id: "ai-intro", persona_id: null, profile: { dimensions: {}, mastery: {} } }), { status: 201, headers: { "Content-Type": "application/json" } })));
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "学习画像" }));
  fireEvent.click(screen.getByRole("button", { name: "建立我的学习画像" }));
  expect(await screen.findByText("让系统先认识你")).toBeInTheDocument();
});
```

- [ ] **Step 2: Verify failure**

Run: `cd frontend && npm test -- --run tests/app.test.tsx`

Expected: FAIL because the dashboard and personal learner action are missing.

- [ ] **Step 3: Integrate navigation and state**

- Make knowledge dashboard the default route.
- Add courses and knowledge routes.
- Keep learner-dependent pages disabled with clear guidance when no learner exists.
- Add a global capture button.
- Load overview and courses on mount and after mutations.
- On personal learner creation, persist learner and open the profile page.

- [ ] **Step 4: Run frontend tests and build**

Run: `cd frontend && npm test -- --run && npm run build`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/api.ts frontend/src/pages/HomePage.tsx frontend/src/pages/ProfilePage.tsx frontend/tests/app.test.tsx frontend/tests/e2e/app.spec.ts
git commit -m "feat: center the product on personal knowledge"
```

---

### Task 9: Seed Example Course, Browser Acceptance and Deployment

**Files:**
- Modify: `backend/tests/test_knowledge_api.py`
- Modify: `frontend/tests/e2e/app.spec.ts`
- Modify: `docs/competition/requirements.md`
- Modify: `docs/competition/architecture.md`
- Modify: `docs/competition/test-report.md`
- Modify: `README.md`

- [ ] **Step 1: Add browser acceptance**

```ts
test("personal knowledge main flow", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "添加知识" }).click();
  await page.getByRole("tab", { name: "快速笔记" }).click();
  await page.getByLabel("课程").selectOption({ label: "人工智能导论" });
  await page.getByLabel("标题").fill("监督学习课堂笔记");
  await page.getByLabel("内容").fill("监督学习使用带标签数据训练模型。");
  await page.getByRole("button", { name: "保存笔记" }).click();
  await expect(page.getByText("已入库")).toBeVisible();
  await page.getByRole("button", { name: "知识库" }).click();
  await page.getByPlaceholder("搜索课程、资料、标签或正文").fill("带标签数据");
  await page.keyboard.press("Enter");
  await expect(page.getByText(/监督学习课堂笔记/)).toBeVisible();
});
```

- [ ] **Step 2: Run full tests**

Run: `./scripts/test-all.sh`

Expected: backend, frontend, build, audit and Playwright all pass.

- [ ] **Step 3: Deploy**

Run:

```bash
DEPLOY_SKIP_TESTS=1 DEPLOY_USER=ubuntu ./scripts/deploy-remote.sh
```

- [ ] **Step 4: Verify public flow**

Use Chrome to verify:

- Personal knowledge dashboard loads.
- Course creation succeeds.
- Markdown upload and quick note succeed.
- Search returns the created knowledge with course and asset title.
- Asset detail opens.
- Mobile capture button remains reachable above the fixed bottom nav.

- [ ] **Step 5: Update competition documentation and commit**

```bash
git add docs/competition README.md frontend/tests/e2e/app.spec.ts
git commit -m "docs: document personal knowledge workspace"
```

## Self-Review

### Spec Coverage

- Course spaces → Tasks 3, 4, 6 and 8.
- File/image/note capture → Tasks 2, 4 and 6.
- Personal knowledge extraction and search → Tasks 1, 2, 3, 4, 5 and 7.
- Dashboard and responsive navigation → Tasks 7, 8 and 9.
- Original source traceability → Tasks 3, 4 and 7.
- Existing agent preservation → Task 8 plus regression suite in Task 9.
- Security and deletion behavior → Tasks 3, 4 and 6.

### Placeholder Scan

No TBD or unresolved implementation markers remain. External OCR availability has an explicit `ready_image_only` fallback.

### Type Consistency

All frontend types use camelCase, matching the API serialization layer. Backend models use snake_case internally and expose camelCase with Pydantic aliases or response adapters. Course and asset IDs remain opaque strings across all tasks.
