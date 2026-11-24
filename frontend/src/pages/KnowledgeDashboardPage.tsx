import {
  ArrowRight,
  BookOpen,
  Boxes,
  FilePlus2,
  FolderPlus,
  LibraryBig,
  LoaderCircle,
  Plus,
  Sparkles,
  Tags,
} from "lucide-react";

import type { KnowledgeOverview } from "../types";

interface Props {
  overview: KnowledgeOverview | null;
  loading?: boolean;
  error?: string | null;
  onCapture: () => void;
  onOpenCourse: (courseId: string) => void;
  onOpenAsset: (assetId: string) => void;
  onOpenKnowledge: () => void;
  onCreateCourse: () => void;
  onRefresh?: () => void;
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? ""
    : date.toLocaleDateString("zh-CN", { month: "short", day: "numeric" });
}

export default function KnowledgeDashboardPage({
  overview,
  loading = false,
  error = null,
  onCapture,
  onOpenCourse,
  onOpenAsset,
  onOpenKnowledge,
  onCreateCourse,
  onRefresh,
}: Props) {
  if (loading && !overview) {
    return (
      <div className="loading-panel knowledge-dashboard-loading">
        <LoaderCircle className="spin" size={22} />
        正在构建你的个人知识空间
      </div>
    );
  }

  const empty = !overview || overview.courseCount === 0;
  const data =
    overview ??
    ({
      courseCount: 0,
      assetCount: 0,
      knowledgeCount: 0,
      pendingCount: 0,
      recentAssets: [],
      courses: [],
      topTags: [],
    } satisfies KnowledgeOverview);

  return (
    <div className="page-stack knowledge-dashboard">
      <section className="knowledge-hero">
        <div>
          <span className="eyebrow">PERSONAL KNOWLEDGE WORKSPACE</span>
          <h2>个人知识工作台</h2>
          <p>
            把自己的学习资料、课堂照片和笔记整理成可搜索的知识文件夹，
            再让学习智能体基于这些真实内容生成资源、路径与辅导。
          </p>
        </div>
        <button className="primary-button" onClick={onCapture}>
          <Plus size={17} />
          添加知识
        </button>
      </section>

      {error ? (
        <div className="error-panel" role="alert">
          {error}
          {onRefresh ? (
            <button className="secondary-button" onClick={onRefresh}>
              重新加载
            </button>
          ) : null}
        </div>
      ) : null}

      <section className="knowledge-stats" aria-label="知识库统计">
        <article>
          <BookOpen size={20} />
          <span>知识文件夹</span>
          <strong>{data.courseCount}</strong>
        </article>
        <article>
          <LibraryBig size={20} />
          <span>个人资料</span>
          <strong>{data.assetCount}</strong>
        </article>
        <article>
          <Sparkles size={20} />
          <span>知识片段</span>
          <strong>{data.knowledgeCount}</strong>
        </article>
        <article>
          <Boxes size={20} />
          <span>待整理</span>
          <strong>{data.pendingCount}</strong>
        </article>
      </section>

      {empty ? (
        <div className="knowledge-empty-state dashboard-empty">
          <span className="knowledge-empty-icon">
            <FolderPlus size={30} />
          </span>
          <h2>创建你的第一个知识文件夹</h2>
          <p>每个文件夹独立存放资料、照片、笔记和提取出的知识点。</p>
          <button className="primary-button" onClick={onCreateCourse}>
            创建第一个文件夹
          </button>
        </div>
      ) : (
        <>
          <section className="knowledge-dashboard-grid">
            <div className="knowledge-panel">
              <div className="knowledge-panel-heading">
                <div>
                  <span className="eyebrow">KNOWLEDGE FOLDERS</span>
                  <h2>我的文件夹</h2>
                </div>
                <button className="text-button" onClick={onCreateCourse}>
                  新建文件夹
                </button>
              </div>
              <div className="knowledge-course-list">
                {data.courses.map((course) => (
                  <button
                    className="knowledge-course-row"
                    key={course.id}
                    onClick={() => onOpenCourse(course.id)}
                  >
                    <span
                      className="course-monogram"
                      style={{ background: course.color }}
                    >
                      {course.title.slice(0, 1)}
                    </span>
                    <div>
                      <strong>{course.title}</strong>
                      <small>
                        {course.assetCount} 份资料 · {course.knowledgeCount} 个片段
                      </small>
                    </div>
                    <ArrowRight size={16} />
                  </button>
                ))}
              </div>
            </div>

            <div className="knowledge-panel recent-panel">
              <div className="knowledge-panel-heading">
                <div>
                  <span className="eyebrow">RECENT CAPTURES</span>
                  <h2>最近添加</h2>
                </div>
                <button className="text-button" onClick={onOpenKnowledge}>
                  查看知识库
                </button>
              </div>
              {data.recentAssets.length ? (
                <div className="recent-asset-list">
                  {data.recentAssets.slice(0, 4).map((asset) => (
                    <button
                      key={asset.id}
                      onClick={() => onOpenAsset(asset.id)}
                    >
                      <span>
                        <FilePlus2 size={17} />
                      </span>
                      <div>
                        <strong>{asset.title}</strong>
                        <small>
                          {asset.courseTitle}
                          {formatDate(asset.createdAt)
                            ? ` · ${formatDate(asset.createdAt)}`
                            : ""}
                        </small>
                      </div>
                      <ArrowRight size={15} />
                    </button>
                  ))}
                </div>
              ) : (
                <div className="recent-empty">
                  <FilePlus2 size={24} />
                  <p>还没有新资料，点击“添加知识”开始。</p>
                </div>
              )}
            </div>
          </section>

          {data.topTags.length ? (
            <section className="knowledge-tags-panel">
              <div>
                <Tags size={18} />
                <strong>常用标签</strong>
              </div>
              <div>
                {data.topTags.map((tag) => (
                  <button key={tag} onClick={onOpenKnowledge}>
                    {tag}
                  </button>
                ))}
              </div>
            </section>
          ) : null}
        </>
      )}
    </div>
  );
}
