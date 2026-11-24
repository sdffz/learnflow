import {
  AlertCircle,
  ArrowRight,
  BookOpen,
  FolderPlus,
  LoaderCircle,
  Pencil,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import LearningConnectorDialog from "../components/LearningConnectorDialog";
import type { Course, CourseInput } from "../types";

interface Props {
  courses: Course[];
  loading: boolean;
  error: string | null;
  onCreate: (input: CourseInput) => Promise<unknown>;
  onOpen: (courseId: string) => void;
  onRefresh: () => void;
  onDelete: (courseId: string) => Promise<void>;
  startCreating?: boolean;
  onUpdate?: (courseId: string, input: CourseInput) => Promise<unknown>;
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? "刚刚更新"
    : date.toLocaleDateString("zh-CN", { month: "short", day: "numeric" });
}

export default function CoursesPage({
  courses,
  loading,
  error,
  onCreate,
  onOpen,
  onRefresh,
  onDelete,
  startCreating = false,
  onUpdate,
}: Props) {
  const [creating, setCreating] = useState(startCreating);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [updating, setUpdating] = useState(false);
  const [connectorOpen, setConnectorOpen] = useState(false);

  useEffect(() => {
    if (startCreating) setCreating(true);
  }, [startCreating]);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (!title.trim() || saving) return;
    setSaving(true);
    setActionError(null);
    setNotice(null);
    try {
      await onCreate({
        title: title.trim(),
        description: description.trim(),
      });
      setNotice(`知识文件夹《${title.trim()}》已创建`);
      setTitle("");
      setDescription("");
      setCreating(false);
    } catch (caught) {
      setActionError(
        caught instanceof Error ? caught.message : "知识文件夹创建失败",
      );
    } finally {
      setSaving(false);
    }
  };

  const remove = async (course: Course) => {
    if (
      !window.confirm(
        `删除《${course.title}》将同时删除其中的资料和知识片段，确定继续吗？`,
      )
    ) {
      return;
    }
    setActionError(null);
    setNotice(null);
    try {
      await onDelete(course.id);
      setNotice(`知识文件夹《${course.title}》已删除`);
    } catch (caught) {
      setActionError(
        caught instanceof Error ? caught.message : "知识文件夹删除失败",
      );
    }
  };

  const beginRename = (course: Course) => {
    setEditingId(course.id);
    setEditTitle(course.title);
    setEditDescription(course.description);
    setActionError(null);
    setNotice(null);
  };

  const rename = async (event: FormEvent, course: Course) => {
    event.preventDefault();
    if (!onUpdate || !editTitle.trim() || updating) return;
    setUpdating(true);
    setActionError(null);
    try {
      await onUpdate(course.id, {
        title: editTitle.trim(),
        description: editDescription.trim(),
      });
      setNotice(`文件夹已重命名为《${editTitle.trim()}》`);
      setEditingId(null);
    } catch (caught) {
      setActionError(
        caught instanceof Error ? caught.message : "文件夹重命名失败",
      );
    } finally {
      setUpdating(false);
    }
  };

  return (
    <div className="page-stack courses-page">
      <section className="knowledge-section-heading">
        <div>
          <span className="eyebrow">COURSE SPACES</span>
          <h2>建立自己的知识文件夹</h2>
          <p>每个文件夹独立存放资料、照片、笔记和提取出的知识点。</p>
        </div>
        <div className="knowledge-section-actions">
          <button
            className="secondary-button"
            onClick={() => {
              setConnectorOpen(true);
              setActionError(null);
              setNotice(null);
            }}
          >
            <BookOpen size={17} />
            连接学习通
          </button>
          <button
            className="primary-button"
            onClick={() => {
              setCreating((value) => !value);
              setActionError(null);
            }}
          >
            <FolderPlus size={17} />
            创建文件夹
          </button>
        </div>
      </section>

      {notice ? (
        <div className="knowledge-notice" role="status">
          {notice}
        </div>
      ) : null}

      {actionError ? (
        <div className="error-panel" role="alert">
          <AlertCircle size={18} />
          <p>{actionError}</p>
        </div>
      ) : null}

      {creating ? (
        <form className="course-create-form" onSubmit={create}>
          <div className="section-heading compact-heading">
            <div>
              <span className="eyebrow">NEW KNOWLEDGE FOLDER</span>
              <h2>创建知识文件夹</h2>
            </div>
          </div>
          <label>
            文件夹名称
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="例如：数据结构、考研英语、课堂重点"
              maxLength={80}
              autoFocus
            />
          </label>
          <label>
            文件夹说明
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="这个文件夹用来整理什么？"
              rows={3}
              maxLength={500}
            />
          </label>
          <div className="course-form-actions">
            <button
              className="text-button"
              type="button"
              onClick={() => setCreating(false)}
            >
              取消
            </button>
            <button
              className="primary-button"
              disabled={saving || !title.trim()}
              type="submit"
            >
              {saving ? <LoaderCircle className="spin" size={17} /> : null}
              {saving ? "正在创建" : "保存文件夹"}
            </button>
          </div>
        </form>
      ) : null}

      {loading ? (
        <div className="loading-panel">
          <LoaderCircle className="spin" size={20} />
          正在读取知识文件夹
        </div>
      ) : null}

      {error ? (
        <div className="error-panel" role="alert">
          <AlertCircle size={18} />
          <p>{error}</p>
          <button className="secondary-button" onClick={onRefresh}>
            <RefreshCw size={16} />
            重新加载
          </button>
        </div>
      ) : null}

      {!loading && !error && courses.length === 0 ? (
        <div className="knowledge-empty-state">
          <span className="knowledge-empty-icon">
            <BookOpen size={28} />
          </span>
          <h2>还没有知识文件夹</h2>
          <p>先创建一个文件夹，再把资料、照片、笔记和知识点放进去。</p>
          <button className="primary-button" onClick={() => setCreating(true)}>
            创建第一个文件夹
          </button>
        </div>
      ) : null}

      {courses.length ? (
        <section className="course-card-grid">
          {courses.map((course) => (
            <article className="course-card" key={course.id}>
              <span
                className="course-color"
                style={{ background: course.color }}
              />
              <div className="course-card-top">
                <span className="course-monogram">
                  {course.title.slice(0, 1)}
                </span>
                <span>{formatDate(course.updatedAt)}</span>
              </div>
              {editingId === course.id ? (
                <form
                  className="course-inline-edit"
                  onSubmit={(event) => void rename(event, course)}
                >
                  <label>
                    文件夹名称
                    <input
                      value={editTitle}
                      onChange={(event) => setEditTitle(event.target.value)}
                      maxLength={80}
                      autoFocus
                    />
                  </label>
                  <label>
                    文件夹说明
                    <textarea
                      value={editDescription}
                      onChange={(event) =>
                        setEditDescription(event.target.value)
                      }
                      rows={2}
                      maxLength={500}
                    />
                  </label>
                  <div className="course-form-actions">
                    <button
                      className="text-button"
                      type="button"
                      onClick={() => setEditingId(null)}
                    >
                      取消
                    </button>
                    <button
                      className="primary-button"
                      type="submit"
                      disabled={updating || !editTitle.trim()}
                    >
                      {updating ? "正在保存" : "保存重命名"}
                    </button>
                  </div>
                </form>
              ) : (
                <>
                  <h3>{course.title}</h3>
                  <p>{course.description || "暂未填写文件夹说明"}</p>
                  <dl className="course-stat-row">
                    <div>
                      <dt>资料</dt>
                      <dd>{course.assetCount}</dd>
                    </div>
                    <div>
                      <dt>知识点</dt>
                      <dd>{course.knowledgeCount}</dd>
                    </div>
                  </dl>
                  <div className="course-card-actions">
                    <button
                      className="secondary-button"
                      onClick={() => onOpen(course.id)}
                    >
                      打开文件夹
                      <ArrowRight size={15} />
                    </button>
                    {onUpdate ? (
                      <button
                        className="course-delete course-rename"
                        aria-label={`重命名 ${course.title}`}
                        onClick={() => beginRename(course)}
                      >
                        <Pencil size={16} />
                      </button>
                    ) : null}
                    <button
                      className="course-delete"
                      aria-label={`删除 ${course.title}`}
                      onClick={() => void remove(course)}
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </>
              )}
            </article>
          ))}
        </section>
      ) : null}

      <LearningConnectorDialog
        open={connectorOpen}
        courses={courses}
        onClose={() => setConnectorOpen(false)}
        onImported={onRefresh}
      />
    </div>
  );
}
