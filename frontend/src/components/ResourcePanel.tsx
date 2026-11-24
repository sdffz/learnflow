import {
  AlertCircle,
  Check,
  Download,
  LoaderCircle,
  Play,
  ShieldCheck,
} from "lucide-react";
import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { api } from "../api";
import type { LearningResource } from "../types";
import MindMap from "./MindMap";
import { AnimationView, CodelabView, QuizView, SlidesView } from "./ResourceViews";

interface Props {
  resources: LearningResource[];
}

const typeLabels: Record<string, string> = {
  document: "讲解文档",
  mindmap: "知识导图",
  quiz: "练习题目",
  codelab: "代码实验",
  slides: "演示课件",
  animation: "动画微课",
};

const order = ["document", "mindmap", "quiz", "codelab", "slides", "animation"];
const downloadExtensions: Record<string, string> = {
  document: "md",
  mindmap: "json",
  quiz: "json",
  codelab: "py",
  slides: "html",
  animation: "html",
};

interface ResourceSource {
  assetId: string;
  assetTitle: string;
  courseTitle: string;
  title: string;
  excerpt: string;
}

function QuizPanel({ resource }: { resource: LearningResource }) {
  const questions = (resource.content.questions ?? []) as Array<{
    id: string;
    stem: string;
    options: string[];
    answer: number;
    explanation: string;
  }>;
  return <QuizView questions={questions} />;
}

function SlidesPanel({ resource }: { resource: LearningResource }) {
  const slides = (resource.content.slides ?? []) as Array<{
    title: string;
    kicker: string;
    body: string;
  }>;
  return <SlidesView slides={slides} />;
}

export default function ResourcePanel({ resources }: Props) {
  const availableTypes = useMemo(
    () => order.filter((type) => resources.some((resource) => resource.type === type)),
    [resources],
  );
  const [activeType, setActiveType] = useState(availableTypes[0] ?? "document");
  const [downloadState, setDownloadState] = useState<{
    kind: "idle" | "loading" | "success" | "error";
    message: string;
  }>({ kind: "idle", message: "" });
  const selectedType = availableTypes.includes(activeType)
    ? activeType
    : availableTypes[0] ?? "document";
  const resource =
    resources.find((item) => item.type === selectedType) ?? resources[0] ?? null;
  const sources =
    (resource?.metadata.sources as ResourceSource[] | undefined) ?? [];

  const downloadResource = async (item: LearningResource) => {
    if (!item.id || downloadState.kind === "loading") return;
    setDownloadState({ kind: "loading", message: "正在准备下载…" });
    try {
      const response = await fetch(api.resourceDownloadUrl(item.id));
      if (!response.ok) throw new Error(`download_failed_${response.status}`);
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = `${item.title}.${downloadExtensions[item.type] ?? "bin"}`;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
      setDownloadState({ kind: "success", message: "已开始下载" });
    } catch {
      setDownloadState({
        kind: "error",
        message: "下载失败，请确认后端服务正常后重试。",
      });
    }
  };

  if (!resources.length) {
    return (
      <div className="resource-empty">
        <Play size={22} />
        <div>
          <strong>资源还没有生成</strong>
          <p>选择知识点并启动多智能体编排。</p>
        </div>
      </div>
    );
  }

  return (
    <div className="resource-panel">
      <div className="resource-tabs" role="tablist" aria-label="学习资源类型">
        {availableTypes.map((type) => (
          <button
            role="tab"
            aria-selected={type === selectedType}
            key={type}
            onClick={() => {
              setActiveType(type);
              setDownloadState({ kind: "idle", message: "" });
            }}
          >
            {typeLabels[type]}
          </button>
        ))}
      </div>

      {resource ? (
        <article className="resource-body">
          <div className="resource-heading">
            <div>
              <span className="resource-kicker">AGENT-CURATED RESOURCE</span>
              <h3>{resource.title}</h3>
            </div>
            <div className="resource-actions">
              <span className="verified">
                <ShieldCheck size={15} />
                已通过质检
              </span>
              {resource.id ? (
                <button
                  className="resource-action-button"
                  disabled={downloadState.kind === "loading"}
                  onClick={() => downloadResource(resource)}
                >
                  {downloadState.kind === "loading" ? (
                    <LoaderCircle className="spin" size={15} />
                  ) : (
                    <Download size={15} />
                  )}
                  下载
                </button>
              ) : null}
            </div>
          </div>

          {downloadState.kind === "success" ? (
            <p className="resource-download-feedback" role="status">
              <Check size={15} />
              {downloadState.message}
            </p>
          ) : null}
          {downloadState.kind === "error" ? (
            <p className="resource-download-error" role="alert">
              <AlertCircle size={15} />
              {downloadState.message}
            </p>
          ) : null}

          {sources.length ? (
            <section className="resource-citations" aria-label="知识来源">
              <strong>知识来源</strong>
              <div>
                {sources.map((source) => (
                  <span key={`${source.assetId}-${source.title}`}>
                    {source.courseTitle} · {source.assetTitle}
                  </span>
                ))}
              </div>
            </section>
          ) : null}

          {resource.type === "document" ? (
            <div className="markdown-body">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {String(resource.content.markdown ?? "")}
              </ReactMarkdown>
            </div>
          ) : null}

          {resource.type === "mindmap" ? (
            <MindMap
              root={
                resource.content.root as {
                  id?: string;
                  label: string;
                  children?: Array<{ id?: string; label: string }>;
                }
              }
            />
          ) : null}

          {resource.type === "quiz" ? <QuizPanel resource={resource} /> : null}

          {resource.type === "codelab" ? (
            <CodelabView
              task={String(resource.content.task ?? "")}
              starter={String(resource.content.starter ?? "")}
              solution={String(resource.content.solution ?? "")}
              expectedOutput={String(resource.content.expected_output ?? "")}
              explanation={String(resource.content.explanation ?? "")}
              language={String(resource.content.language ?? "python")}
            />
          ) : null}

          {resource.type === "slides" ? <SlidesPanel resource={resource} /> : null}

          {resource.type === "animation" ? (
            <AnimationView
              html={String(resource.content.html ?? "")}
              title={resource.title}
            />
          ) : null}
        </article>
      ) : null}
    </div>
  );
}
