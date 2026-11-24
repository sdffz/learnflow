import {
  ArrowRight,
  BrainCircuit,
  ChartNoAxesCombined,
  Route,
  Sparkles,
} from "lucide-react";

import type { Learner } from "../types";
import {
  deriveNextAction,
  type WorkspaceState,
  type WorkspaceTarget,
} from "../workspace";

interface Props {
  learner: Learner;
  workspace: WorkspaceState;
  active: WorkspaceTarget;
  onNavigate: (target: WorkspaceTarget) => void;
}

export default function WorkspaceBar({
  learner,
  workspace,
  active,
  onNavigate,
}: Props) {
  const action = deriveNextAction(learner, workspace);
  const profileReady = Object.keys(learner.profile.dimensions).length >= 6;
  const resourceLabel =
    workspace.latestRunStatus === "partial"
      ? `学习资源 ${workspace.resourceCount}/6 · 部分完成`
      : workspace.resourceCount > 0
        ? `学习资源 ${workspace.resourceCount}/6`
        : "学习资源 尚未生成";

  return (
    <section className="workspace-bar" aria-label="学习工作台状态">
      <div className="workspace-context">
        <span>人工智能导论 · {workspace.activeTopic}</span>
        <small>
          当前学生：{learner.name} · 自由切换功能，状态会持续保留
        </small>
      </div>

      <div className="workspace-statuses">
        <button
          data-ready={profileReady}
          data-active={active === "profile"}
          onClick={() => onNavigate("profile")}
          aria-current={active === "profile" ? "page" : undefined}
          aria-label={profileReady ? "学习画像 已完成" : "学习画像 待完善"}
        >
          <BrainCircuit size={15} />
          {profileReady ? "画像已完成" : "画像待完善"}
        </button>
        <button
          data-ready={
            workspace.resourceCount === 6 &&
            workspace.latestRunStatus === "completed"
          }
          data-active={active === "studio"}
          onClick={() => onNavigate("studio")}
          aria-current={active === "studio" ? "page" : undefined}
          aria-label={resourceLabel}
        >
          <Sparkles size={15} />
          {resourceLabel}
        </button>
        <button
          data-ready={workspace.pathGenerated}
          data-active={active === "path"}
          onClick={() => onNavigate("path")}
          aria-current={active === "path" ? "page" : undefined}
          aria-label={workspace.pathGenerated ? "学习路径 已生成" : "学习路径 待规划"}
        >
          <Route size={15} />
          {workspace.pathGenerated ? "路径已生成" : "路径待规划"}
        </button>
        <button
          data-ready={workspace.lastAssessmentScore !== null}
          data-active={active === "assessment"}
          onClick={() => onNavigate("assessment")}
          aria-current={active === "assessment" ? "page" : undefined}
          aria-label={
            workspace.lastAssessmentScore === null
              ? "学习评估 尚未完成"
              : `学习评估 最近 ${workspace.lastAssessmentScore} 分`
          }
        >
          <ChartNoAxesCombined size={15} />
          {workspace.lastAssessmentScore === null
            ? "评估未完成"
            : `最近评估 ${workspace.lastAssessmentScore}`}
        </button>
      </div>

      <div className="workspace-next">
        <div>
          <span>下一步</span>
          <small>{action.reason}</small>
        </div>
        <button onClick={() => onNavigate(action.target)}>
          {action.label}
          <ArrowRight size={16} />
        </button>
      </div>
    </section>
  );
}
