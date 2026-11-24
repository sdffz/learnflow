import {
  AlertCircle,
  ArrowLeft,
  Download,
  FileText,
  Image,
  LoaderCircle,
  RefreshCw,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { knowledgeApi } from "../api";
import type { AssetDetail } from "../types";

interface Props {
  assetId: string;
  onBack: () => void;
}

const statusLabels = {
  processing: "仍在处理",
  ready: "已完成知识提取",
  ready_image_only: "图片已保存，文字识别未启用",
  failed: "处理失败",
} as const;

export default function AssetDetailPage({ assetId, onBack }: Props) {
  const [asset, setAsset] = useState<AssetDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setAsset(await knowledgeApi.getAsset(assetId));
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "资料加载失败",
      );
    } finally {
      setLoading(false);
    }
  }, [assetId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <div className="loading-panel asset-detail-loading">
        <LoaderCircle className="spin" size={22} />
        正在打开资料
      </div>
    );
  }

  if (error || !asset) {
    return (
      <div className="page-stack">
        <button className="knowledge-back" onClick={onBack}>
          <ArrowLeft size={16} />
          返回
        </button>
        <div className="error-panel" role="alert">
          <AlertCircle size={18} />
          <p>{error ?? "资料不存在"}</p>
          <button className="secondary-button" onClick={() => void load()}>
            <RefreshCw size={16} />
            重新加载
          </button>
        </div>
      </div>
    );
  }

  const fileUrl = knowledgeApi.assetFileUrl(asset.id);

  return (
    <div className="page-stack asset-detail">
      <button className="knowledge-back" onClick={onBack}>
        <ArrowLeft size={16} />
        返回个人知识库
      </button>

      <section className="asset-detail-hero">
        <span className="asset-detail-icon">
          {asset.kind === "image" ? (
            <Image size={28} />
          ) : (
            <FileText size={28} />
          )}
        </span>
        <div>
          <span className="eyebrow">{asset.courseTitle}</span>
          <h2>{asset.title}</h2>
          <div className="asset-detail-meta">
            <span>{statusLabels[asset.status]}</span>
            <span>{asset.knowledgeCount} 个知识片段</span>
            {asset.originalName ? <span>{asset.originalName}</span> : null}
          </div>
        </div>
        {asset.fileAvailable ? (
          <a
            className="secondary-button"
            href={fileUrl}
            target="_blank"
            rel="noreferrer"
          >
            <Download size={16} />
            打开原始文件
          </a>
        ) : null}
      </section>

      {asset.status === "ready_image_only" ? (
        <div className="knowledge-inline-warning">
          <AlertCircle size={18} />
          {asset.error ?? "当前环境未启用文字识别，但原始图片已经保存。"}
        </div>
      ) : null}

      <div className="asset-detail-layout">
        <section className="asset-source-panel">
          <div className="knowledge-panel-heading">
            <div>
              <span className="eyebrow">SOURCE CONTENT</span>
              <h2>资料正文</h2>
            </div>
          </div>
          {asset.kind === "image" ? (
            <img
              className="asset-source-image"
              src={fileUrl}
              alt={asset.title}
            />
          ) : null}
          <pre className="asset-source-text">
            {asset.content || "这份资料暂时没有可显示的文字内容。"}
          </pre>
        </section>

        <aside className="asset-side-panel">
          <section>
            <span className="eyebrow">TAGS</span>
            <h3>标签</h3>
            <div className="asset-detail-tags">
              {asset.tags.length ? (
                asset.tags.map((tag) => <span key={tag}>{tag}</span>)
              ) : (
                <p>尚未添加标签</p>
              )}
            </div>
          </section>

          <section>
            <span className="eyebrow">KNOWLEDGE CHUNKS</span>
            <h3>提取的知识</h3>
            {asset.chunks.length ? (
              <div className="asset-chunk-list">
                {asset.chunks.map((chunk) => (
                  <article key={chunk.id}>
                    <strong>{chunk.title}</strong>
                    <p>{chunk.excerpt}</p>
                  </article>
                ))}
              </div>
            ) : (
              <p className="asset-no-chunks">尚未提取到知识片段。</p>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
