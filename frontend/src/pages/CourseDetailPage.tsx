import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  BookMarked,
  BookOpen,
  FileText,
  Image,
  LoaderCircle,
  NotebookPen,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { knowledgeApi } from "../api";
import type { Course, KnowledgeAsset, KnowledgeChunk } from "../types";

interface Props {
  course: Course;
  onBack: () => void;
  onCapture: (courseId: string) => void;
  onOpenAsset: (assetId: string) => void;
}

const kindLabels = {
  file: "课程文件",
  image: "课堂图片",
  note: "快速笔记",
} as const;

const statusLabels = {
  processing: "处理中",
  ready: "已入库",
  ready_image_only: "图片已保存",
  failed: "处理失败",
} as const;

function AssetIcon({ kind }: { kind: KnowledgeAsset["kind"] }) {
  if (kind === "image") return <Image size={20} />;
  if (kind === "note") return <NotebookPen size={20} />;
  return <FileText size={20} />;
}

export default function CourseDetailPage({
  course,
  onBack,
  onCapture,
  onOpenAsset,
}: Props) {
  const [assets, setAssets] = useState<KnowledgeAsset[]>([]);
  const [chunks, setChunks] = useState<KnowledgeChunk[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextAssets, nextChunks] = await Promise.all([
        knowledgeApi.listAssets(course.id),
        knowledgeApi.search("", undefined, course.id),
      ]);
      setAssets(nextAssets);
      setChunks(nextChunks);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "文件夹内容加载失败",
      );
    } finally {
      setLoading(false);
    }
  }, [course.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const removeAsset = async (asset: KnowledgeAsset) => {
    if (!window.confirm(`删除资料《${asset.title}》及其知识片段？`)) return;
    setError(null);
    try {
      await knowledgeApi.deleteAsset(asset.id);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "资料删除失败");
    }
  };

  const tags = Array.from(new Set(assets.flatMap((asset) => asset.tags)));

  return (
    <div className="page-stack course-detail-page">
      <button className="knowledge-back" onClick={onBack}>
        <ArrowLeft size={16} />
        返回知识文件夹
      </button>

      <section className="course-detail-hero">
        <span className="course-monogram large">
          {course.title.slice(0, 1)}
        </span>
        <div>
          <span className="eyebrow">PERSONAL KNOWLEDGE FOLDER</span>
          <h2>{course.title}</h2>
          <p>{course.description || "把资料、照片、笔记和知识点集中到这里。"}</p>
          <div className="course-detail-meta">
            <span>{course.assetCount} 份资料</span>
            <span>{course.knowledgeCount} 个知识片段</span>
          </div>
        </div>
        <button
          className="primary-button"
          onClick={() => onCapture(course.id)}
        >
          <Plus size={17} />
          添加知识
        </button>
      </section>

      {tags.length ? (
        <div className="course-tag-row" aria-label="课程标签">
          {tags.map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
      ) : null}

      <section className="folder-knowledge-panel">
        <div className="knowledge-section-heading compact-heading">
          <div>
            <span className="eyebrow">EXTRACTED KNOWLEDGE</span>
            <h2>文件夹知识点</h2>
          </div>
          <span className="soft-badge">{chunks.length} 条</span>
        </div>
        {chunks.length ? (
          <div className="folder-knowledge-list">
            {chunks.slice(0, 12).map((chunk) => (
              <article key={chunk.id}>
                <span className="folder-knowledge-icon">
                  <BookMarked size={16} />
                </span>
                <div>
                  <strong>{chunk.title}</strong>
                  <p>{chunk.excerpt}</p>
                  <small>来源：{chunk.assetTitle}</small>
                </div>
                <button onClick={() => onOpenAsset(chunk.assetId)}>
                  查看来源
                  <ArrowRight size={14} />
                </button>
              </article>
            ))}
          </div>
        ) : (
          <p className="folder-knowledge-empty">
            添加资料或快速笔记后，知识点会自动出现在这里。
          </p>
        )}
      </section>

      <section className="knowledge-section-heading compact-heading">
        <div>
          <span className="eyebrow">COURSE MATERIALS</span>
          <h2>文件夹资料</h2>
        </div>
        <span className="soft-badge">{assets.length} 项</span>
      </section>

      {loading ? (
        <div className="loading-panel">
          <LoaderCircle className="spin" size={20} />
          正在读取文件夹内容
        </div>
      ) : null}

      {error ? (
        <div className="error-panel" role="alert">
          <AlertCircle size={18} />
          <p>{error}</p>
          <button className="secondary-button" onClick={() => void load()}>
            <RefreshCw size={16} />
            重新加载资料
          </button>
        </div>
      ) : null}

      {!loading && !error && assets.length === 0 ? (
        <div className="knowledge-empty-state">
          <span className="knowledge-empty-icon">
            <BookOpen size={28} />
          </span>
          <h2>这个文件夹还没有资料</h2>
          <p>上传老师课件、拍下板书，或直接记录第一条课堂笔记。</p>
          <button
            className="primary-button"
            onClick={() => onCapture(course.id)}
          >
            添加第一份资料
          </button>
        </div>
      ) : null}

      {assets.length ? (
        <section className="asset-list">
          {assets.map((asset) => (
            <article className="asset-card" key={asset.id}>
              {asset.kind === "image" ? (
                <img
                  className="asset-thumbnail"
                  src={knowledgeApi.assetFileUrl(asset.id)}
                  alt=""
                />
              ) : (
                <span className="asset-kind-icon">
                  <AssetIcon kind={asset.kind} />
                </span>
              )}
              <div className="asset-card-main">
                <div className="asset-card-meta">
                  <span>{kindLabels[asset.kind]}</span>
                  <span data-status={asset.status}>
                    {statusLabels[asset.status]}
                  </span>
                </div>
                <h3>{asset.title}</h3>
                <p>{asset.summary || "资料已保存，等待查看正文。"}</p>
                <div className="asset-card-tags">
                  {asset.tags.slice(0, 4).map((tag) => (
                    <span key={tag}>{tag}</span>
                  ))}
                  <small>{asset.knowledgeCount} 个知识片段</small>
                </div>
              </div>
              <div className="asset-card-actions">
                <button
                  className="secondary-button"
                  onClick={() => onOpenAsset(asset.id)}
                >
                  打开资料
                  <ArrowRight size={15} />
                </button>
                <button
                  className="course-delete"
                  aria-label={`删除资料 ${asset.title}`}
                  onClick={() => void removeAsset(asset)}
                >
                  <Trash2 size={16} />
                </button>
              </div>
            </article>
          ))}
        </section>
      ) : null}
    </div>
  );
}
