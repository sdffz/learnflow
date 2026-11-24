import {
  AlertCircle,
  Camera,
  Check,
  FileUp,
  LoaderCircle,
  NotebookPen,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";

import { knowledgeApi } from "../api";
import type { AssetDetail, Course } from "../types";

type CaptureMode = "file" | "image" | "note";

interface Props {
  courses: Course[];
  initialCourseId?: string;
  onClose: () => void;
  onCreated: (asset: AssetDetail) => void;
}

function parseTags(value: string): string[] {
  return value
    .split(/[,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function messageFor(caught: unknown): string {
  return caught instanceof Error ? caught.message : "保存失败，请稍后重试";
}

export default function CaptureDialog({
  courses,
  initialCourseId,
  onClose,
  onCreated,
}: Props) {
  const [mode, setMode] = useState<CaptureMode>("file");
  const [courseId, setCourseId] = useState(
    initialCourseId ?? courses[0]?.id ?? "",
  );
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [tags, setTags] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [image, setImage] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{
    kind: "success" | "warning" | "error";
    message: string;
  } | null>(null);

  const selectedCourse = useMemo(
    () => courses.find((course) => course.id === courseId) ?? null,
    [courseId, courses],
  );
  const canSubmit =
    Boolean(courseId) &&
    !busy &&
    (mode === "note"
      ? Boolean(title.trim() && content.trim())
      : mode === "file"
        ? Boolean(file)
        : Boolean(image));

  const changeMode = (nextMode: CaptureMode) => {
    setMode(nextMode);
    setFeedback(null);
  };

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setFeedback(null);
    try {
      let asset: AssetDetail;
      if (mode === "note") {
        asset = await knowledgeApi.createNote(courseId, {
          title: title.trim(),
          content: content.trim(),
          tags: parseTags(tags),
        });
      } else {
        const chosenFile = mode === "file" ? file : image;
        if (!chosenFile) return;
        asset = await knowledgeApi.uploadAsset(courseId, chosenFile, {
          title: title.trim(),
          tags: parseTags(tags),
        });
      }

      if (asset.status === "ready_image_only") {
        setFeedback({
          kind: "warning",
          message:
            asset.error ??
            "图片已保存，但当前环境未启用文字识别，可补充一条快速笔记。",
        });
      } else {
        setFeedback({
          kind: "success",
          message: `已入库，提取 ${asset.knowledgeCount} 个知识片段`,
        });
      }
      onCreated(asset);
    } catch (caught) {
      setFeedback({ kind: "error", message: messageFor(caught) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="capture-backdrop" role="presentation">
      <section
        className="capture-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="capture-title"
      >
        <header className="capture-header">
          <div>
            <span className="eyebrow">ADD TO PERSONAL KNOWLEDGE</span>
            <h2 id="capture-title">添加知识</h2>
            <p>文件、课堂照片和临时想法，都可以归入自己的知识文件夹。</p>
          </div>
          <button
            className="capture-close"
            aria-label="关闭添加知识"
            onClick={onClose}
            type="button"
          >
            <X size={19} />
          </button>
        </header>

        <div className="capture-tabs" role="tablist" aria-label="知识添加方式">
          <button
            role="tab"
            aria-selected={mode === "file"}
            onClick={() => changeMode("file")}
            type="button"
          >
            <FileUp size={17} />
            上传文件
          </button>
          <button
            role="tab"
            aria-selected={mode === "image"}
            onClick={() => changeMode("image")}
            type="button"
          >
            <Camera size={17} />
            拍照/图片
          </button>
          <button
            role="tab"
            aria-selected={mode === "note"}
            onClick={() => changeMode("note")}
            type="button"
          >
            <NotebookPen size={17} />
            快速笔记
          </button>
        </div>

        <div className="capture-course-row">
          <label>
            存放文件夹
            <select
              value={courseId}
              onChange={(event) => setCourseId(event.target.value)}
              disabled={!courses.length}
            >
              {!courses.length ? <option value="">请先创建文件夹</option> : null}
              {courses.map((course) => (
                <option value={course.id} key={course.id}>
                  {course.title}
                </option>
              ))}
            </select>
          </label>
          {selectedCourse ? (
            <p>
              将保存到 <strong>{selectedCourse.title}</strong>
            </p>
          ) : null}
        </div>

        {mode === "file" ? (
          <label className="capture-dropzone">
            <FileUp size={30} />
            <strong>{file ? file.name : "选择学习资料"}</strong>
            <span>支持 PDF、PPTX、DOCX、Markdown、TXT，最大 25 MB</span>
            <input
              aria-label="选择资料文件"
              type="file"
              accept=".pdf,.pptx,.docx,.md,.txt"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </label>
        ) : null}

        {mode === "image" ? (
          <label className="capture-dropzone capture-camera">
            <Camera size={30} />
            <strong>{image ? image.name : "拍照或从相册选择"}</strong>
            <span>照片会保存在当前课程；支持时自动识别中英文文字</span>
            <input
              aria-label="拍照或选择图片"
              type="file"
              accept="image/*"
              capture="environment"
              onChange={(event) => setImage(event.target.files?.[0] ?? null)}
            />
          </label>
        ) : null}

        <div className="capture-fields">
          <label>
            资料标题
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder={
                mode === "note" ? "例如：课堂重点" : "留空则使用文件名"
              }
            />
          </label>
          <label>
            标签
            <input
              value={tags}
              onChange={(event) => setTags(event.target.value)}
              placeholder="例如：图论, 课堂笔记"
            />
          </label>
          {mode === "note" ? (
            <label className="capture-note-content">
              资料内容
              <textarea
                value={content}
                onChange={(event) => setContent(event.target.value)}
                placeholder="记录概念、问题、老师强调的重点或你的理解"
                rows={6}
              />
            </label>
          ) : null}
        </div>

        {feedback ? (
          <div
            className={`capture-feedback ${feedback.kind}`}
            role={feedback.kind === "error" ? "alert" : "status"}
          >
            {feedback.kind === "error" ? (
              <AlertCircle size={18} />
            ) : (
              <Check size={18} />
            )}
            {feedback.message}
          </div>
        ) : null}

        <footer className="capture-actions">
          <button
            className="text-button"
            onClick={onClose}
            type="button"
          >
            稍后再说
          </button>
          <button
            className="primary-button"
            disabled={!canSubmit}
            onClick={() => void submit()}
            type="button"
          >
            {busy ? <LoaderCircle className="spin" size={17} /> : null}
            {busy
              ? "正在保存"
              : mode === "note"
                ? "保存笔记"
                : mode === "image"
                  ? "保存图片"
                  : "开始上传"}
          </button>
        </footer>
      </section>
    </div>
  );
}
