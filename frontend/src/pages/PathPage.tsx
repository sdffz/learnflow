import {
  AlertCircle,
  ArrowRight,
  Check,
  Circle,
  LoaderCircle,
  RefreshCw,
  Route,
  Sparkles,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { api } from "../api";
import type { Learner, LearningPath } from "../types";
import type { WorkspaceState, WorkspaceTarget } from "../workspace";

interface Props {
  learner: Learner | null;
  onNeedLearner: () => void;
  onWorkspaceChange: (patch: Partial<WorkspaceState>) => void;
  onNavigate: (target: WorkspaceTarget) => void;
}

export default function PathPage({
  learner,
  onNeedLearner,
  onWorkspaceChange,
  onNavigate,
}: Props) {
  const [path, setPath] = useState<LearningPath | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadPath = useCallback(() => {
    if (!learner) return;
    let active = true;
    setLoading(true);
    setError(null);
    api
      .createPath(learner.id)
      .then((value) => {
        if (active) {
          setPath(value);
          onWorkspaceChange({ pathGenerated: true });
        }
      })
      .catch((caught) => {
        if (active) setError(caught instanceof Error ? caught.message : "路径生成失败");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [learner, onWorkspaceChange]);

  useEffect(() => loadPath(), [loadPath]);

  if (!learner) {
    return (
      <div className="empty-page">
        <Route size={28} />
        <h2>还没有学习路径</h2>
        <p>路径会结合目标、薄弱点和学习节奏自动生成。</p>
        <button className="primary-button" onClick={onNeedLearner}>
          建立我的学习画像
        </button>
      </div>
    );
  }

  return (
    <div className="page-stack">
      <section className="path-intro">
        <div>
          <span className="eyebrow">ADAPTIVE ROUTE</span>
          <h2>不是固定课程目录，而是你的下一步。</h2>
          <p>节点顺序和推荐媒介会随画像、练习与评估结果变化。</p>
        </div>
        <div className="route-glyph" aria-hidden="true">
          <Sparkles size={26} />
        </div>
      </section>

      {loading ? (
        <div className="loading-panel">
          <LoaderCircle className="spin" size={20} />
          正在计算知识依赖和学习顺序
        </div>
      ) : null}

      {error ? (
        <div className="error-panel" role="alert">
          <AlertCircle size={18} />
          <p>{error}</p>
          <button
            className="secondary-button"
            disabled={loading}
            onClick={() => loadPath()}
          >
            <RefreshCw className={loading ? "spin" : undefined} size={16} />
            重新生成路径
          </button>
        </div>
      ) : null}

      {path ? (
        <>
          <div className="path-summary">
            <div>
              <span className="eyebrow">CURRENT PLAN</span>
              <h3>{path.title}</h3>
            </div>
            <p>{path.adjustment_note}</p>
          </div>

          <ol className="path-list">
            {path.nodes.map((node, index) => (
              <li className={node.status} key={node.id}>
                <div className="path-marker">
                  {node.status === "completed" ? (
                    <Check size={16} />
                  ) : node.status === "current" ? (
                    <ArrowRight size={16} />
                  ) : (
                    <Circle size={13} />
                  )}
                </div>
                <article>
                  <div className="path-node-top">
                    <span>STEP {String(index + 1).padStart(2, "0")}</span>
                    <strong>{node.status === "current" ? "当前节点" : "待学习"}</strong>
                  </div>
                  <h3>{node.title}</h3>
                  <span className="topic-pill">{node.topic}</span>
                  <p>{node.recommendation}</p>
                  <div className="resource-chips">
                    {node.resource_types.map((type) => (
                      <span key={type}>{type}</span>
                    ))}
                  </div>
                  {node.dependency ? (
                    <small>前置节点：{node.dependency}</small>
                  ) : null}
                  {node.status === "current" ? (
                    <button
                      className="path-resource-action"
                      onClick={() => onNavigate("studio")}
                    >
                      查看匹配资源
                      <ArrowRight size={14} />
                    </button>
                  ) : null}
                </article>
              </li>
            ))}
          </ol>
          <div className="page-next-actions">
            <div>
              <strong>路径已经生成</strong>
              <span>完成一次评估，让掌握度继续更新学习计划。</span>
            </div>
            <button
              className="primary-button"
              onClick={() => onNavigate("assessment")}
            >
              进入学习评估
              <ArrowRight size={16} />
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}
