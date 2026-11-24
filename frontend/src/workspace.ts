import type { Learner } from "./types";

export type WorkspaceTarget =
  | "home"
  | "profile"
  | "studio"
  | "path"
  | "tutor"
  | "assessment";

export type RunStatus =
  | "idle"
  | "queued"
  | "running"
  | "completed"
  | "partial"
  | "failed";

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
const RUN_STATUSES: RunStatus[] = [
  "idle",
  "queued",
  "running",
  "completed",
  "partial",
  "failed",
];

export function createDefaultWorkspace(): WorkspaceState {
  return {
    courseId: "ai-intro",
    // Empty means "let the profile decide". A hardcoded topic silently
    // ignored whatever the learner said in the interview.
    activeTopic: "",
    latestRunId: null,
    latestRunStatus: "idle",
    resourceCount: 0,
    pathGenerated: false,
    lastAssessmentScore: null,
    lastAssessmentAt: null,
  };
}

export function workspaceStorageKey(userId?: string): string {
  return userId ? `${STORAGE_KEY}:${userId}` : STORAGE_KEY;
}

export function loadWorkspace(storageKey = STORAGE_KEY): WorkspaceState {
  try {
    const parsed = JSON.parse(
      window.localStorage.getItem(storageKey) ?? "null",
    ) as Partial<WorkspaceState> | null;
    if (
      !parsed ||
      parsed.courseId !== "ai-intro" ||
      typeof parsed.activeTopic !== "string" ||
      !RUN_STATUSES.includes(parsed.latestRunStatus as RunStatus) ||
      !Number.isFinite(parsed.resourceCount)
    ) {
      return createDefaultWorkspace();
    }
    return { ...createDefaultWorkspace(), ...parsed };
  } catch {
    return createDefaultWorkspace();
  }
}

export function saveWorkspace(
  state: WorkspaceState,
  storageKey = STORAGE_KEY,
): void {
  window.localStorage.setItem(storageKey, JSON.stringify(state));
}

export function clearWorkspace(storageKey = STORAGE_KEY): void {
  window.localStorage.removeItem(storageKey);
}

export function deriveNextAction(
  learner: Learner | null,
  workspace: WorkspaceState,
): NextAction {
  if (!learner) {
    return {
      target: "home",
      label: "建立学习画像",
      reason: "先记录你的学习目标、基础和偏好",
    };
  }

  if (Object.keys(learner.profile.dimensions).length < 6) {
    return {
      target: "profile",
      label: "完善学习画像",
      reason: "画像维度不足 6 个，需要补充学习情况",
    };
  }

  if (
    workspace.latestRunStatus === "queued" ||
    workspace.latestRunStatus === "running"
  ) {
    return {
      target: "studio",
      label: "恢复生成进度",
      reason: `${workspace.activeTopic}资源正在生成`,
    };
  }

  if (workspace.latestRunStatus === "failed") {
    return {
      target: "studio",
      label: "重试资源生成",
      reason: "最近一次资源运行失败",
    };
  }

  if (!workspace.latestRunId || workspace.resourceCount === 0) {
    return {
      target: "studio",
      label: "生成个性化资源",
      reason: `尚未生成${workspace.activeTopic}学习资源`,
    };
  }

  if (!workspace.pathGenerated) {
    return {
      target: "path",
      label: "规划学习路径",
      reason: "资源已就绪，下一步是确定学习顺序",
    };
  }

  if (workspace.lastAssessmentScore === null) {
    return {
      target: "assessment",
      label: "完成学习评估",
      reason: "路径已生成，尚未检验掌握情况",
    };
  }

  return {
    target: "tutor",
    label: "进入智能辅导",
    reason: "已完成一次评估，可针对薄弱点继续提问",
  };
}
