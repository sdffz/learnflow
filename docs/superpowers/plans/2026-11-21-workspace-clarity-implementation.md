# LearnFlow Free Workspace Clarity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保留自由侧边导航的前提下，为学生端增加持续可见的学习上下文、动态工作台首页、下一步操作和可恢复的学习状态。

**Architecture:** App 持有学习者与 WorkspaceState，工作台纯函数负责下一步推导，WorkspaceBar 统一展示状态；各页面通过回调和 `onNavigate` 更新状态，不改变后端智能体流程。状态保存在 localStorage，资源运行通过 existing `GET /api/runs/{id}` 恢复。

**Tech Stack:** React 19、TypeScript、Vitest、Testing Library、Playwright、Vite；现有 FastAPI API 保持不变。

## Global Constraints

- 不修改后端画像抽取、知识库、模型网关或多智能体编排。
- 保留现有六个自由导航入口：首页、学习画像、资源工作室、学习路径、智能辅导、效果评估。
- `WorkspaceState.courseId` 固定为 `ai-intro`；课程不匹配时清空状态。
- 所有状态更新来自成功 API 结果或明确运行状态，失败不得错误推进。
- 新资源运行必须重新计算资源数，并使旧路径和旧评估失效。
- partial 运行显示“部分完成”，不得显示 6/6 全部成功。
- 切换学生会删除 `learnflow_learner` 和 `learnflow_workspace`。
- 每个交互都有可见反馈；保留现有 Tutor/下载错误反馈。
- 生产构建默认使用同源 `/api`。
- 全部完成后重新部署到 `124.223.49.44` 并验证公网。

## File Structure

- Create `frontend/src/workspace.ts`：状态类型、默认值、持久化、下一步推导。
- Create `frontend/src/components/WorkspaceBar.tsx`：全局课程、主题、状态胶囊、主操作。
- Modify `frontend/src/App.tsx`：集中管理学习者和 WorkspaceState，处理导航与切换学生。
- Modify `frontend/src/pages/HomePage.tsx`：无学生显示选人，有学生显示工作台摘要。
- Modify `frontend/src/pages/ProfilePage.tsx`：完成后进入资源生成。
- Modify `frontend/src/pages/StudioPage.tsx`：主题回写、运行 ID 恢复、完成后状态更新。
- Modify `frontend/src/pages/PathPage.tsx`：路径完成状态与下一步。
- Modify `frontend/src/pages/TutorPage.tsx`：显示当前主题并进入评估。
- Modify `frontend/src/pages/AssessmentPage.tsx`：回写评估结果、返回工作台。
- Modify `frontend/src/styles.css`：状态栏、工作台首页、状态胶囊、动作区。
- Create `frontend/tests/workspace.test.ts`。
- Create `frontend/tests/workspace-ui.test.tsx`。
- Modify `frontend/tests/e2e/app.spec.ts`。

---

### Task 1: Workspace State and Next-Action Derivation

**Files:**
- Create: `frontend/src/workspace.ts`
- Create: `frontend/tests/workspace.test.ts`

**Interfaces:**
- Produces: `WorkspaceState`, `WorkspaceTarget`, `NextAction`.
- Produces: `createDefaultWorkspace()`, `loadWorkspace()`, `saveWorkspace()`, `clearWorkspace()`.
- Produces: `deriveNextAction(learner: Learner | null, workspace: WorkspaceState): NextAction`.

- [ ] **Step 1: Write failing tests**

```ts
import {
  createDefaultWorkspace,
  deriveNextAction,
  loadWorkspace,
  saveWorkspace,
} from "../src/workspace";
import type { Learner } from "../src/types";

const learner: Learner = {
  id: "l1", name: "学生", course_id: "ai-intro", persona_id: "beginner",
  profile: {
    dimensions: {
      a: { value: "a", evidence: "a", confidence: 0.8, updated_at: "" },
      b: { value: "b", evidence: "b", confidence: 0.8, updated_at: "" },
      c: { value: "c", evidence: "c", confidence: 0.8, updated_at: "" },
      d: { value: "d", evidence: "d", confidence: 0.8, updated_at: "" },
      e: { value: "e", evidence: "e", confidence: 0.8, updated_at: "" },
      f: { value: "f", evidence: "f", confidence: 0.8, updated_at: "" },
    },
    mastery: {},
  },
};

test("idle learner is directed to resource generation", () => {
  expect(deriveNextAction(learner, createDefaultWorkspace()).target).toBe("studio");
});

test("completed resources without a path are directed to path planning", () => {
  const state = {
    ...createDefaultWorkspace(),
    latestRunId: "r1",
    latestRunStatus: "completed" as const,
    resourceCount: 6,
  };
  expect(deriveNextAction(learner, state).target).toBe("path");
});

test("existing assessment is directed to tutoring", () => {
  const state = {
    ...createDefaultWorkspace(),
    latestRunId: "r1",
    latestRunStatus: "completed" as const,
    resourceCount: 6,
    pathGenerated: true,
    lastAssessmentScore: 88,
  };
  expect(deriveNextAction(learner, state).target).toBe("tutor");
});

test("invalid stored workspace falls back to defaults", () => {
  localStorage.setItem("learnflow_workspace", "{broken");
  expect(loadWorkspace()).toEqual(createDefaultWorkspace());
});

test("saved workspace can be restored", () => {
  const state = { ...createDefaultWorkspace(), activeTopic: "机器学习" };
  saveWorkspace(state);
  expect(loadWorkspace()).toEqual(state);
});
```

- [ ] **Step 2: Run and verify failure**

Run: `cd frontend && npm test -- --run tests/workspace.test.ts`  
Expected: FAIL because `src/workspace` does not exist.

- [ ] **Step 3: Implement the state module**

```ts
export type WorkspaceTarget = "home" | "profile" | "studio" | "path" | "tutor" | "assessment";
export type RunStatus = "idle" | "queued" | "running" | "completed" | "partial" | "failed";

export interface WorkspaceState {
  courseId: "ai-intro";
  activeTopic: string;
  latestRunId: string | null;
  latestRunStatus: RunStatus;
  resourceCount: number;
  pathGenerated: boolean;
  lastAssessmentScore: number | null;
  lastAssessmentAt: string | null;
}

export interface NextAction {
  target: WorkspaceTarget;
  label: string;
  reason: string;
}

const STORAGE_KEY = "learnflow_workspace";

export function createDefaultWorkspace(): WorkspaceState {
  return {
    courseId: "ai-intro",
    activeTopic: "神经网络",
    latestRunId: null,
    latestRunStatus: "idle",
    resourceCount: 0,
    pathGenerated: false,
    lastAssessmentScore: null,
    lastAssessmentAt: null,
  };
}

export function loadWorkspace(): WorkspaceState {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null");
    if (
      !parsed ||
      parsed.courseId !== "ai-intro" ||
      typeof parsed.activeTopic !== "string" ||
      !["idle", "queued", "running", "completed", "partial", "failed"].includes(parsed.latestRunStatus) ||
      !Number.isFinite(parsed.resourceCount)
    ) {
      return createDefaultWorkspace();
    }
    return { ...createDefaultWorkspace(), ...parsed };
  } catch {
    return createDefaultWorkspace();
  }
}

export function saveWorkspace(state: WorkspaceState): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

export function clearWorkspace(): void {
  localStorage.removeItem(STORAGE_KEY);
}

export function deriveNextAction(learner: Learner | null, state: WorkspaceState): NextAction {
  if (!learner) {
    return { target: "home", label: "选择演示学生", reason: "先建立当前学习者会话" };
  }
  if (Object.keys(learner.profile.dimensions).length < 6) {
    return { target: "profile", label: "完善学习画像", reason: "画像维度不足 6 个" };
  }
  if (state.latestRunStatus === "queued" || state.latestRunStatus === "running") {
    return { target: "studio", label: "恢复生成进度", reason: `${state.activeTopic}资源正在生成` };
  }
  if (state.latestRunStatus === "failed") {
    return { target: "studio", label: "重试资源生成", reason: "最近一次资源运行失败" };
  }
  if (!state.latestRunId || state.resourceCount === 0) {
    return { target: "studio", label: "生成个性化资源", reason: "尚未生成当前主题资源" };
  }
  if (!state.pathGenerated) {
    return { target: "path", label: "规划学习路径", reason: "资源已就绪，下一步是确定学习顺序" };
  }
  if (state.lastAssessmentScore === null) {
    return { target: "assessment", label: "完成学习评估", reason: "路径已生成，尚未检验掌握情况" };
  }
  return { target: "tutor", label: "进入智能辅导", reason: "已完成一次评估，可针对薄弱点继续提问" };
}
```

- [ ] **Step 4: Run and verify pass**

Run: `cd frontend && npm test -- --run tests/workspace.test.ts && npm run build`  
Expected: workspace tests pass and TypeScript build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/workspace.ts frontend/tests/workspace.test.ts
git commit -m "feat: add persistent workspace state model"
```

---

### Task 2: Global Workspace Status Bar

**Files:**
- Create: `frontend/src/components/WorkspaceBar.tsx`
- Create: `frontend/tests/workspace-ui.test.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: `WorkspaceState`, `deriveNextAction()`, learner profile.
- Produces: `WorkspaceBar({ learner, workspace, onNavigate })`.

- [ ] **Step 1: Write failing component tests**

```tsx
test("workspace bar shows current topic and next action", () => {
  render(<WorkspaceBar learner={learner} workspace={state} onNavigate={navigate} />);
  expect(screen.getByText(/人工智能导论 · 神经网络/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "规划学习路径" }));
  expect(navigate).toHaveBeenCalledWith("path");
});

test("partial resources are not reported as complete", () => {
  render(<WorkspaceBar learner={learner} workspace={{ ...state, latestRunStatus: "partial", resourceCount: 4 }} onNavigate={navigate} />);
  expect(screen.getByText("资源 4/6 · 部分完成")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run and verify failure**

Run: `cd frontend && npm test -- --run tests/workspace-ui.test.tsx`  
Expected: FAIL because `WorkspaceBar` is missing.

- [ ] **Step 3: Implement status bar**

Render:

- Course line `人工智能导论 · {workspace.activeTopic}`.
- Four state buttons: 画像、资源、路径、评估.
- Next action reason and button from `deriveNextAction`.
- Use `aria-current` when relevant.

```tsx
const action = deriveNextAction(learner, workspace);
const profileReady = Object.keys(learner.profile.dimensions).length >= 6;
const resourceLabel =
  workspace.latestRunStatus === "partial"
    ? `资源 ${workspace.resourceCount}/6 · 部分完成`
    : workspace.resourceCount
      ? `资源 ${workspace.resourceCount}/6`
      : "尚未生成资源";
```

- [ ] **Step 4: Run tests and build**

Run: `cd frontend && npm test -- --run tests/workspace-ui.test.tsx && npm run build`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/WorkspaceBar.tsx frontend/src/styles.css frontend/tests/workspace-ui.test.tsx
git commit -m "feat: add persistent learning context bar"
```

---

### Task 3: Dynamic Workspace Home

**Files:**
- Modify: `frontend/src/pages/HomePage.tsx`
- Modify: `frontend/tests/workspace-ui.test.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Adds props: `learner: Learner | null`, `workspace: WorkspaceState`, `onNavigate(target)`, `onSwitchLearner()`.
- No learner: current three-persona picker.
- Learner present: dashboard with current profile, topic, statuses, `继续学习`.

- [ ] **Step 1: Write failing dashboard test**

```tsx
test("home shows resume dashboard when learner exists", () => {
  render(<HomePage personas={[]} loading={false} error={null} busyPersona={null}
    learner={learner} workspace={state} onStart={vi.fn()} onRetry={vi.fn()}
    onNavigate={navigate} onSwitchLearner={vi.fn()} />);
  expect(screen.getByText("继续你的学习")).toBeInTheDocument();
  expect(screen.queryByText("选择一位演示学生")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /继续学习/ }));
  expect(navigate).toHaveBeenCalledWith("path");
});
```

- [ ] **Step 2: Verify failure**

Run: `cd frontend && npm test -- --run tests/workspace-ui.test.tsx`

- [ ] **Step 3: Implement dashboard branch**

The learner dashboard contains:

- Greeting and current goal/weakness.
- Four compact metrics.
- A prominent next-action card.
- Buttons `继续学习`, `查看学习路径`, `切换演示学生`.
- No persona cards.

- [ ] **Step 4: Verify and commit**

Run: `cd frontend && npm test -- --run tests/workspace-ui.test.tsx && npm run build`

```bash
git add frontend/src/pages/HomePage.tsx frontend/src/styles.css frontend/tests/workspace-ui.test.tsx
git commit -m "feat: turn home into a learning workspace"
```

---

### Task 4: Central App State and Navigation

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/tests/e2e/app.spec.ts`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- App loads and saves `WorkspaceState`.
- App renders `WorkspaceBar` under topbar for any selected learner.
- Adds `navigate(target)`, `updateWorkspace(patch)`, `switchLearner()`.

- [ ] **Step 1: Add failing e2e assertions**

```ts
await expect(page.getByText(/人工智能导论 · 神经网络/)).toBeVisible();
await expect(page.getByRole("button", { name: "规划学习路径" })).toBeVisible();
```

- [ ] **Step 2: Verify failure**

Run: `cd frontend && npm run test:e2e`

- [ ] **Step 3: Implement central state**

```tsx
const [workspace, setWorkspace] = useState<WorkspaceState>(() => loadWorkspace());
useEffect(() => saveWorkspace(workspace), [workspace]);
const updateWorkspace = (patch: Partial<WorkspaceState>) => setWorkspace((current) => ({ ...current, ...patch }));
const switchLearner = () => {
  persistLearner(null);
  clearWorkspace();
  setWorkspace(createDefaultWorkspace());
  setActive("home");
};
```

Pass relevant state and callbacks to all pages.

- [ ] **Step 4: Run tests and commit**

Run: `cd frontend && npm test -- --run && npm run build && npm run test:e2e`

```bash
git add frontend/src/App.tsx frontend/src/styles.css frontend/tests/e2e/app.spec.ts
git commit -m "feat: connect free navigation to shared workspace state"
```

---

### Task 5: Studio State Restoration and Generation Updates

**Files:**
- Modify: `frontend/src/pages/StudioPage.tsx`
- Modify: `frontend/tests/e2e/app.spec.ts`

**Interfaces:**
- Consumes workspace fields and `onWorkspaceChange(patch)`.
- On mount with `latestRunId`, fetch and restore run snapshot.
- New run resets downstream path and assessment.

- [ ] **Step 1: Write failing e2e checks**

After generation:

```ts
await expect(page.getByText("资源 6/6")).toBeVisible();
await page.reload();
await page.getByRole("button", { name: "资源工作室", exact: true }).click();
await expect(page.getByRole("tab", { name: "动画微课" })).toBeVisible();
```

- [ ] **Step 2: Verify failure**

Run: `cd frontend && npm run test:e2e`

- [ ] **Step 3: Implement**

- Topic `select` calls `onWorkspaceChange({ activeTopic: topic })`.
- Before create run: `{ latestRunStatus: "queued", resourceCount: 0, pathGenerated: false, lastAssessmentScore: null, lastAssessmentAt: null }`.
- On run created: set `latestRunId`.
- On final snapshot: set run status and resource count.
- `useEffect` restores snapshot from `workspace.latestRunId`.
- `404`: clear run ID and show visible error.
- Completion actions route to path/tutor.

- [ ] **Step 4: Verify and commit**

Run: `cd frontend && npm test -- --run && npm run build && npm run test:e2e`

```bash
git add frontend/src/pages/StudioPage.tsx frontend/tests/e2e/app.spec.ts
git commit -m "feat: restore and track resource generation state"
```

---

### Task 6: Page-Level Next Actions and Assessment State

**Files:**
- Modify: `frontend/src/pages/ProfilePage.tsx`
- Modify: `frontend/src/pages/PathPage.tsx`
- Modify: `frontend/src/pages/TutorPage.tsx`
- Modify: `frontend/src/pages/AssessmentPage.tsx`
- Modify: `frontend/tests/workspace-ui.test.tsx`
- Modify: `frontend/tests/e2e/app.spec.ts`

**Interfaces:**
- Each page accepts `onNavigate(target)`.
- Path sets `pathGenerated: true` after success.
- Assessment sets score/time after success.

- [ ] **Step 1: Add failing component/e2e assertions**

- Profile renders `用画像生成资源`.
- Path renders `完成学习评估`.
- Tutor shows `当前主题：神经网络`.
- Assessment renders `返回学习工作台`.
- E2E confirms `路径已生成` and `最近评估 100`.

- [ ] **Step 2: Verify failures**

Run: `cd frontend && npm test -- --run tests/workspace-ui.test.tsx && npm run test:e2e`

- [ ] **Step 3: Implement callbacks and actions**

- Profile complete CTA → studio.
- Path success → `onWorkspaceChange({ pathGenerated: true })`; CTA → assessment.
- Tutor topic chip and CTA → assessment.
- Assessment success → `onAssessmentChange({ score })`; result CTA → home.
- Retest does not clear persisted assessment until a new successful result.

- [ ] **Step 4: Run and commit**

Run: `./scripts/test-all.sh`

```bash
git add frontend/src/pages frontend/tests/workspace-ui.test.tsx frontend/tests/e2e/app.spec.ts
git commit -m "feat: add clear next actions across learning pages"
```

---

### Task 7: Production Acceptance and Redeploy

**Files:**
- Modify: `docs/competition/test-report.md`

**Interfaces:**
- Consumes final frontend build and existing deployment scripts.
- Produces updated public deployment at `http://124.223.49.44/`.

- [ ] **Step 1: Run full tests**

Run: `./scripts/test-all.sh`  
Expected: backend, frontend, build and Playwright all pass.

- [ ] **Step 2: Deploy**

Run:

```bash
DEPLOY_SKIP_TESTS=1 DEPLOY_USER=ubuntu ./scripts/deploy-remote.sh
```

- [ ] **Step 3: Run public E2E**

Navigate `http://124.223.49.44/`, verify:

- Workspace bar persists after reload.
- Resource count, path status and assessment score survive refresh.
- All next-action buttons route correctly.
- Switching learners clears the bar and returns to persona selection.

- [ ] **Step 4: Commit docs**

```bash
git add docs/competition/test-report.md
git commit -m "docs: record workspace clarity verification"
```

---

## Self-Review

### Spec Coverage

- Global context and state pills → Tasks 1–2.
- Dynamic home → Task 3.
- Central state and clear reset → Task 4.
- Resource persistence/restoration and partial handling → Task 5.
- Page next actions, path/assessment updates → Task 6.
- Production verification → Task 7.

### Placeholder Scan

No TBD, TODO, unspecified UI copy, or untested production behavior remains. Expected failure modes and exact verification commands are included.

### Type Consistency

`WorkspaceState`, `WorkspaceTarget`, `RunStatus`, `updateWorkspace`, `onWorkspaceChange`, and `onNavigate` use the same field and callback names across all tasks. localStorage keys remain `learnflow_learner` and `learnflow_workspace`.
