import { AlertCircle, ArrowRight, Clock3, LoaderCircle, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api } from "../api";
import AgentTimeline from "../components/AgentTimeline";
import ResourcePanel from "../components/ResourcePanel";
import type {
  AgentEvent,
  Course,
  Learner,
  LearningResource,
} from "../types";
import type { WorkspaceState, WorkspaceTarget } from "../workspace";

interface Props {
  learner: Learner | null;
  onNeedLearner: () => void;
  workspace: WorkspaceState;
  onWorkspaceChange: (patch: Partial<WorkspaceState>) => void;
  onNavigate: (target: WorkspaceTarget) => void;
  courses: Course[];
}

const topics = [
  "神经网络",
  "机器学习",
  "搜索与问题求解",
  "人工智能伦理",
  "人工智能概述",
];

/**
 * Pick the study topic from the learner's own profile.
 *
 * The studio used to default to "神经网络" regardless of the interview, so a
 * learner who said 数据结构薄弱 still received 神经网络 material. The weak
 * point wins because that is what the resources most need to address, then the
 * stated interest, then the goal.
 */
export function topicFromProfile(learner: Learner | null): string {
  if (!learner) return "";
  const pick = (name: string) => learner.profile.dimensions[name]?.value?.trim();
  for (const name of ["当前薄弱点", "兴趣方向", "学习目标"]) {
    const value = pick(name);
    if (!value) continue;
    // "数据结构比较薄弱" -> "数据结构"; keep the noun, drop the qualifier.
    const cleaned = value
      .replace(
        /(比较|有点|非常|很|特别|较|不太)?(薄弱|较弱|弱|差|不熟悉|不熟|不懂|没掌握|没学过|不太行|不会).*$/,
        "",
      )
      .replace(/^(对|关于)/, "")
      .trim();
    if (cleaned) return cleaned;
  }
  return "";
}

export default function StudioPage({
  learner,
  onNeedLearner,
  workspace,
  onWorkspaceChange,
  onNavigate,
  courses,
}: Props) {
  const [topic, setTopic] = useState(workspace.activeTopic);
  const [courseId, setCourseId] = useState(courses[0]?.id ?? "");
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [resources, setResources] = useState<LearningResource[]>([]);
  const [generating, setGenerating] = useState(false);
  const generatingRef = useRef(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setTopic(workspace.activeTopic);
  }, [workspace.activeTopic, learner?.id]);

  // With no explicit topic yet, follow the profile instead of a fixed default.
  useEffect(() => {
    if (workspace.activeTopic) return;
    if (!learner) return;
    const derived = topicFromProfile(learner);
    if (derived) {
      setTopic(derived);
      onWorkspaceChange({ activeTopic: derived });
    }
  }, [learner, onWorkspaceChange, workspace.activeTopic]);

  useEffect(() => {
    if (courses.some((course) => course.id === courseId)) return;
    setCourseId(courses[0]?.id ?? "");
  }, [courseId, courses]);

  useEffect(() => {
    if (
      !learner ||
      !workspace.latestRunId ||
      resources.length > 0 ||
      generatingRef.current
    ) {
      return;
    }
    let active = true;
    generatingRef.current = true;
    setGenerating(true);
    setError(null);
    api
      .getRun(workspace.latestRunId)
      .then((snapshot) => {
        if (!active) return;
        setEvents(snapshot.events);
        setResources(snapshot.resources);
        onWorkspaceChange({
          latestRunStatus: snapshot.status as WorkspaceState["latestRunStatus"],
          resourceCount: snapshot.resources.length,
        });
      })
      .catch(() => {
        if (!active) return;
        onWorkspaceChange({
          latestRunId: null,
          latestRunStatus: "idle",
          resourceCount: 0,
        });
        setError("上次资源运行已失效，请重新生成。");
      })
      .finally(() => {
        if (active) {
          generatingRef.current = false;
          setGenerating(false);
        }
      });
    return () => {
      active = false;
      generatingRef.current = false;
    };
  }, [learner, onWorkspaceChange, resources.length, workspace.latestRunId]);

  if (!learner) {
    return (
      <div className="empty-page">
        <Sparkles size={28} />
        <h2>先建立学习画像</h2>
        <p>智能体需要画像来调整难度、媒介和资源组合。</p>
        <button className="primary-button" onClick={onNeedLearner}>
          建立我的学习画像
        </button>
      </div>
    );
  }

  const generate = async () => {
    setGenerating(true);
    generatingRef.current = true;
    setError(null);
    setEvents([]);
    setResources([]);
    onWorkspaceChange({
      activeTopic: topic,
      latestRunId: null,
      latestRunStatus: "queued",
      resourceCount: 0,
      pathGenerated: false,
      lastAssessmentScore: null,
      lastAssessmentAt: null,
    });
    try {
      const run = await api.createRun(learner.id, topic, courseId || undefined);
      onWorkspaceChange({
        latestRunId: run.id,
        latestRunStatus: "queued",
      });
      await api.streamRun(run.id, (event) => {
        setEvents((current) =>
          current.some((item) => item.sequence === event.sequence)
            ? current
            : [...current, event],
        );
        if (event.data.resource?.id) {
          setResources((current) => [...current, event.data.resource!]);
        }
        if (event.phase === "run" && event.status === "running") {
          onWorkspaceChange({ latestRunStatus: "running" });
        }
      });
      const snapshot = await api.getRun(run.id);
      setEvents(snapshot.events);
      setResources(snapshot.resources);
      onWorkspaceChange({
        latestRunStatus: snapshot.status as WorkspaceState["latestRunStatus"],
        resourceCount: snapshot.resources.length,
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "资源生成失败");
      onWorkspaceChange({ latestRunStatus: "failed" });
    } finally {
      generatingRef.current = false;
      setGenerating(false);
    }
  };

  const completed = resources.filter((resource) => resource.status === "verified").length;
  const progress = generating ? Math.max(8, Math.round((events.length / 10) * 100)) : completed ? 100 : 0;
  const failed =
    workspace.latestRunStatus === "failed" || Boolean(error);
  const selectedCourse =
    courses.find((course) => course.id === courseId) ?? null;
  const canGenerate =
    Boolean(topic.trim()) &&
    Boolean(selectedCourse) &&
    (selectedCourse?.knowledgeCount ?? 0) > 0;

  return (
    <div className="page-stack">
      <section className="studio-toolbar">
        <div>
          <span className="eyebrow">MULTI-AGENT STUDIO</span>
          <h2>把画像变成一套可学习的内容</h2>
          <p>课程分析、资源生成与质检由不同角色协作完成。</p>
        </div>
        <div className="studio-controls">
          <label>
            知识来源
            <select
              value={courseId}
              onChange={(event) => setCourseId(event.target.value)}
            >
              {courses.map((course) => (
                <option value={course.id} key={course.id}>
                  {course.title}
                </option>
              ))}
            </select>
          </label>
          <label>
            学习主题
            <input
              list="learning-topic-options"
              value={topic}
              onChange={(event) => {
                const nextTopic = event.target.value;
                setTopic(nextTopic);
                onWorkspaceChange({ activeTopic: nextTopic });
              }}
              placeholder="输入课程知识点"
            />
            <datalist id="learning-topic-options">
              {topics.map((item) => (
                <option value={item} key={item} />
              ))}
            </datalist>
          </label>
          <button
            className="primary-button"
            disabled={generating || !canGenerate}
            onClick={generate}
          >
            {generating ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}
            {generating
              ? "智能体协作中"
              : failed
                ? "重试生成六类资源"
                : "生成六类资源"}
          </button>
        </div>
      </section>

      <div className="studio-knowledge-context">
        <Sparkles size={16} />
        {selectedCourse ? (
          <span>
            将使用《{selectedCourse.title}》中的{" "}
            <strong>{selectedCourse.knowledgeCount}</strong>{" "}
            个个人知识片段生成并标注来源
          </span>
        ) : (
          <span>请先在知识文件夹创建文件夹并添加资料</span>
        )}
      </div>

      <section className="generation-overview">
        <div className="progress-copy">
          <span>资源完成度</span>
          <strong>{completed} / 6</strong>
        </div>
        <div className="progress-track">
          <span style={{ width: `${progress}%` }} />
        </div>
        <span className="time-note">
          <Clock3 size={15} />
          长任务采用进度事件，不阻塞页面
        </span>
      </section>

      {error ? (
        <div className="error-panel" role="alert">
          <AlertCircle size={19} />
          <p>{error}</p>
        </div>
      ) : null}

      <div className="studio-layout">
        <aside className="timeline-panel">
          <div className="mini-heading">
            <div>
              <span className="eyebrow">AGENT TRACE</span>
              <h3>协作时间线</h3>
            </div>
            <span className="run-dot" />
          </div>
          <AgentTimeline events={events} />
        </aside>
        <section className="resource-workspace">
          <ResourcePanel resources={resources} />
        </section>
      </div>

      {completed > 0 && !generating ? (
        <div className="page-next-actions">
          <div>
            <strong>资源已经准备好</strong>
            <span>接下来确定学习顺序，或直接针对疑问继续学习。</span>
          </div>
          <button className="primary-button" onClick={() => onNavigate("path")}>
            查看学习路径
            <ArrowRight size={16} />
          </button>
          <button className="secondary-button" onClick={() => onNavigate("tutor")}>
            进入智能辅导
          </button>
        </div>
      ) : null}
    </div>
  );
}
