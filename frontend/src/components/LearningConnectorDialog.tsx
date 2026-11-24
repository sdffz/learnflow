import {
  AlertCircle,
  ArrowRight,
  Check,
  FolderInput,
  LoaderCircle,
  QrCode,
  RefreshCw,
  ShieldCheck,
  Unplug,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";

import { ApiError, learningConnectorApi } from "../api";
import type {
  Course,
  LearningFolderMapping,
  LearningImportDetail,
  LearningImportJob,
  LearningImportPreview,
  LearningLogin,
} from "../types";

interface Props {
  open: boolean;
  courses: Course[];
  onClose: () => void;
  onImported: () => void;
}

type Phase =
  | "loading"
  | "disabled"
  | "unreachable"
  | "disconnected"
  | "connected"
  | "qr"
  | "preview"
  | "mapping"
  | "progress";

const LOGIN_POLL_MS = 1500;
const JOB_POLL_MS = 1200;
const ACTIVE_JOB_STATUSES = new Set([
  "queued",
  "reading",
  "downloading",
  "parsing",
]);

const ERROR_MESSAGES: Record<string, string> = {
  connector_disabled: "学习通连接功能尚未启用。",
  login_expired: "二维码已过期，请重新生成。",
  login_cancelled: "本次扫码已取消。",
  login_not_found: "扫码会话不存在，请重新生成二维码。",
  session_expired: "学习通会话已过期，请重新扫码连接。",
  verification_required: "学习通要求额外身份验证，请重新扫码确认。",
  upstream_unavailable: "暂时无法访问学习通，请稍后重试。",
  upstream_changed: "学习通页面结构发生变化，请稍后重试或使用 ZIP 导入。",
  preview_not_found: "课程预览已过期，请重新读取。",
  course_not_found: "目标知识文件夹不存在或无权访问。",
  nothing_selected: "请至少选择一门课程。",
  nothing_to_import: "所选课程没有可导入的文档或视频链接。",
  import_not_found: "同步任务不存在或已失效。",
  invalid_job_state: "当前同步任务状态不允许此操作。",
};

function errorMessage(caught: unknown): string {
  if (caught instanceof ApiError) {
    return ERROR_MESSAGES[caught.message] ?? `操作失败：${caught.message}`;
  }
  return caught instanceof Error ? caught.message : "操作失败，请稍后重试";
}

function formatBytes(value: number): string {
  if (!value) return "大小待获取";
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function statusLabel(status: LearningImportJob["status"]): string {
  return {
    queued: "等待同步",
    reading: "正在读取课程",
    downloading: "正在下载资料",
    parsing: "正在提取知识",
    completed: "导入完成",
    partial_failed: "部分资料失败",
    cancelled: "已取消同步",
    session_expired: "学习通会话过期",
  }[status];
}

function isActiveJob(job: LearningImportJob | null): boolean {
  return Boolean(job && ACTIVE_JOB_STATUSES.has(job.status));
}

export default function LearningConnectorDialog({
  open,
  courses,
  onClose,
  onImported,
}: Props) {
  const dialogRef = useRef<HTMLElement>(null);
  const zipInputRef = useRef<HTMLInputElement>(null);
  const pollingRef = useRef(false);
  const completedNoticeRef = useRef<string | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [remoteNickname, setRemoteNickname] = useState<string | null>(null);
  const [login, setLogin] = useState<LearningLogin | null>(null);
  const [now, setNow] = useState(Date.now());
  const [preview, setPreview] = useState<LearningImportPreview | null>(null);
  const [selectedCourses, setSelectedCourses] = useState<Set<string>>(
    new Set(),
  );
  const [mappings, setMappings] = useState<
    Record<string, LearningFolderMapping>
  >({});
  const [jobDetail, setJobDetail] = useState<LearningImportDetail | null>(null);

  const reset = useCallback(() => {
    setPhase("loading");
    setBusy(null);
    setError(null);
    setNotice(null);
    setRemoteNickname(null);
    setLogin(null);
    setPreview(null);
    setSelectedCourses(new Set());
    setMappings({});
    setJobDetail(null);
    completedNoticeRef.current = null;
  }, []);

  const loadStatus = useCallback(async () => {
    setPhase("loading");
    setError(null);
    try {
      const result = await learningConnectorApi.status();
      if (!result.enabled) {
        setPhase("disabled");
        return;
      }
      if (result.connection?.status === "connected") {
        setRemoteNickname(result.connection.remoteNickname);
        setPhase("connected");
        return;
      }
      setPhase("disconnected");
    } catch (caught) {
      setError(errorMessage(caught));
      // A failed status probe is not the same as "not connected". Falling
      // through to 未连接 used to render a QR button that could only fail.
      setPhase("unreachable");
    }
  }, []);

  const reloadStatus = useCallback(() => {
    void loadStatus();
  }, [loadStatus]);

  useEffect(() => {
    if (!open) return;
    reset();
    void loadStatus();
  }, [open, reset, loadStatus]);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  useEffect(() => {
    if (!open || phase !== "qr") return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [open, phase]);

  const loadPreview = useCallback(async () => {
    setBusy("preview");
    setError(null);
    setNotice("正在读取课程和资料目录…");
    try {
      const result = await learningConnectorApi.createPreview();
      openPreview(result);
    } catch (caught) {
      setError(errorMessage(caught));
      setNotice(null);
      setPhase("connected");
    } finally {
      setBusy(null);
    }
  }, [courses]);

  const openPreview = useCallback(
    (result: LearningImportPreview) => {
      setPreview(result);
      const initialMappings: Record<string, LearningFolderMapping> = {};
      for (const course of result.courses) {
        const existing = courses.find((item) => item.title === course.title);
        initialMappings[course.id] = existing
          ? {
              previewCourseId: course.id,
              mode: "merge",
              targetCourseId: existing.id,
            }
          : {
              previewCourseId: course.id,
              mode: "new",
              folderTitle: course.title,
            };
      }
      setSelectedCourses(new Set());
      setMappings(initialMappings);
      setPhase("preview");
      // A live account lists its courses, but chaoxing renders the document
      // list client-side, so the extractor can come back with zero files. Say
      // that plainly instead of implying the account is empty.
      if (!result.courses.length) {
        setNotice("没有找到可导入的课程资料。");
      } else if (!result.totalDocuments && !result.totalVideoLinks) {
        setNotice(
          `已读取 ${result.courses.length} 门课程，但没能自动提取到文档清单。` +
            "学习通的资料目录需要在浏览器里渲染，建议按课程下载资料后用 ZIP 方式导入。",
        );
      } else {
        setNotice(
          `已读取 ${result.courses.length} 门课程，请选择要导入的内容。`,
        );
      }
    },
    [courses],
  );

  const loadCourseDocuments = useCallback(
    async (courseId: string) => {
      if (!preview) return;
      setBusy(`docs:${courseId}`);
      setError(null);
      try {
        const updated = await learningConnectorApi.loadCourseDocuments(
          preview.id,
          courseId,
        );
        // Keep the existing selections and mappings; only the files changed.
        setPreview(updated);
        const course = updated.courses.find((item) => item.id === courseId);
        const count = course?.documents.filter((f) => f.supported).length ?? 0;
        setNotice(
          count
            ? `已读取「${course?.title ?? "该课程"}」的 ${count} 份资料。`
            : `「${course?.title ?? "该课程"}」没有可导入的文档，可能只有视频或测验。`,
        );
      } catch (caught) {
        setError(errorMessage(caught));
      } finally {
        setBusy(null);
      }
    },
    [preview],
  );

  const pollLogin = useCallback(async () => {
    if (!login || pollingRef.current) return;
    pollingRef.current = true;
    try {
      const result = await learningConnectorApi.pollLogin(login.id);
      if (result.status === "connected") {
        setRemoteNickname(result.remoteNickname);
        setLogin(null);
        setNotice("学习通连接成功，正在读取课程…");
        await loadPreview();
        return;
      }
      if (result.status === "confirming") {
        setNotice(
          result.remoteNickname
            ? `${result.remoteNickname} 已在学习通确认，等待登录完成…`
            : "已扫码，请在学习通 App 中点击确认。",
        );
        return;
      }
      if (result.status === "pending") {
        setNotice("等待使用学习通 App 扫码…");
        return;
      }
      // The server no longer knows this login (expired, restarted, or the
      // runtime data was reset). Reset to a usable state instead of leaving
      // the user on a screen whose only button can never succeed.
      const reason = result.message ?? result.status;
      setLogin(null);
      setPhase("disconnected");
      if (reason === "login_not_found" || reason === "login_expired") {
        setNotice("二维码已失效，请重新生成。");
        setError(null);
      } else {
        setError(
          ERROR_MESSAGES[reason] ?? "扫码未完成，请重新生成二维码。",
        );
      }
    } catch (caught) {
      // A vanished login surfaces as a thrown ApiError, not as a status field.
      const code = caught instanceof ApiError ? caught.message : null;
      if (code === "login_not_found" || code === "login_expired") {
        setLogin(null);
        setPhase("disconnected");
        setNotice("二维码已失效，请重新生成。");
        setError(null);
      } else {
        setError(errorMessage(caught));
      }
    } finally {
      pollingRef.current = false;
    }
  }, [loadPreview, login]);

  useEffect(() => {
    if (!open || phase !== "qr" || !login) return;
    void pollLogin();
    const timer = window.setInterval(() => {
      void pollLogin();
    }, LOGIN_POLL_MS);
    return () => window.clearInterval(timer);
  }, [login, open, phase, pollLogin]);

  const refreshJob = useCallback(async (jobId: string) => {
    setBusy((current) => current ?? "job-refresh");
    try {
      const detail = await learningConnectorApi.getImport(jobId);
      setJobDetail(detail);
      setError(
        detail.job.errorMessage && detail.job.status !== "completed"
          ? detail.job.errorMessage
          : null,
      );
      if (
        detail.job.status === "completed" &&
        completedNoticeRef.current !== jobId
      ) {
        completedNoticeRef.current = jobId;
        setNotice("导入完成，资料已进入个人知识库。");
        onImported();
      }
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy((current) => (current === "job-refresh" ? null : current));
    }
  }, [onImported]);

  useEffect(() => {
    const job = jobDetail?.job;
    if (!open || phase !== "progress" || !job || !isActiveJob(job)) return;
    void refreshJob(job.id);
    const timer = window.setInterval(() => {
      void refreshJob(job.id);
    }, JOB_POLL_MS);
    return () => window.clearInterval(timer);
  }, [jobDetail?.job?.id, jobDetail?.job?.status, open, phase, refreshJob]);

  const startLogin = async () => {
    if (busy) return;
    setBusy("login");
    setError(null);
    setNotice("正在向学习通申请一次性登录二维码…");
    try {
      const started = await learningConnectorApi.startLogin();
      setLogin(started);
      setPhase("qr");
      setNow(Date.now());
      setNotice("请使用学习通 App 扫描二维码。");
    } catch (caught) {
      setError(errorMessage(caught));
      setNotice(null);
    } finally {
      setBusy(null);
    }
  };

  const uploadZip = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || busy) return;
    setBusy("zip");
    setError(null);
    setNotice(`正在检查 ZIP 资料包《${file.name}》…`);
    try {
      const result = await learningConnectorApi.previewZip(file);
      openPreview(result);
    } catch (caught) {
      setError(errorMessage(caught));
      setNotice(null);
    } finally {
      setBusy(null);
    }
  };

  const refreshLogin = async () => {
    if (!login || busy) return;
    setBusy("login-refresh");
    setError(null);
    try {
      const refreshed = await learningConnectorApi.refreshLogin(login.id);
      setLogin(refreshed);
      setNow(Date.now());
      setNotice("二维码已刷新，旧二维码立即失效。");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  };

  const disconnect = async () => {
    if (busy) return;
    if (!window.confirm("断开后会删除知序保存的学习通会话，已导入资料仍会保留。继续吗？")) {
      return;
    }
    setBusy("disconnect");
    setError(null);
    try {
      await learningConnectorApi.disconnect();
      setRemoteNickname(null);
      setPhase("disconnected");
      setNotice("学习通连接已断开，会话已删除。");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  };

  const close = async () => {
    if (busy) return;
    if (login && phase === "qr") {
      setBusy("close");
      try {
        await learningConnectorApi.cancelLogin(login.id);
      } catch {
        // Closing the local dialog must still work if the QR already expired.
      } finally {
        setBusy(null);
      }
    }
    onClose();
  };

  const toggleCourse = (courseId: string) => {
    setSelectedCourses((current) => {
      const next = new Set(current);
      if (next.has(courseId)) next.delete(courseId);
      else next.add(courseId);
      return next;
    });
    setError(null);
  };

  const toggleAll = () => {
    if (!preview) return;
    const importable = preview.courses
      .filter(
        (course) =>
          course.videoLinks.length > 0 ||
          course.documents.some((file) => file.supported),
      )
      .map((course) => course.id);
    setSelectedCourses((current) =>
      current.size === importable.length ? new Set() : new Set(importable),
    );
    setError(null);
  };

  const goToMapping = () => {
    if (!selectedCourses.size) {
      setError("请至少选择一门课程。");
      return;
    }
    setError(null);
    setPhase("mapping");
    setNotice("确认每门课程要新建文件夹还是合并到已有文件夹。");
  };

  const updateMapping = (
    courseId: string,
    patch: Partial<LearningFolderMapping>,
  ) => {
    setMappings((current) => ({
      ...current,
      [courseId]: {
        ...current[courseId],
        ...patch,
        previewCourseId: courseId,
      },
    }));
  };

  const startImport = async () => {
    if (!preview || busy) return;
    const selectedMappings = preview.courses
      .filter((course) => selectedCourses.has(course.id))
      .map((course) => mappings[course.id])
      .filter(Boolean);
    if (
      selectedMappings.some(
        (mapping) =>
          mapping.mode === "merge" && !mapping.targetCourseId?.trim(),
      )
    ) {
      setError("合并模式的课程必须选择一个已有文件夹。");
      return;
    }
    setBusy("import");
    setError(null);
    setNotice("正在创建后台同步任务…");
    try {
      const job = await learningConnectorApi.createImport(
        preview.id,
        selectedMappings,
      );
      setJobDetail({ job, items: [] });
      setPhase("progress");
      setNotice(`同步任务已启动，共 ${job.totalItems} 项。`);
    } catch (caught) {
      setError(errorMessage(caught));
      setNotice(null);
    } finally {
      setBusy(null);
    }
  };

  const cancelImport = async () => {
    if (!jobDetail || busy) return;
    setBusy("job-cancel");
    setError(null);
    try {
      const job = await learningConnectorApi.cancelImport(jobDetail.job.id);
      setJobDetail((current) => (current ? { ...current, job } : current));
      setNotice("同步任务已取消，已完成资料会保留。");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  };

  const retryImport = async () => {
    if (!jobDetail || busy) return;
    setBusy("job-retry");
    setError(null);
    try {
      const job = await learningConnectorApi.retryImport(jobDetail.job.id);
      setJobDetail((current) => (current ? { ...current, job } : current));
      setNotice("失败项已重新加入同步队列。");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  };

  const qrSeconds = login
    ? Math.max(
        0,
        Math.ceil((new Date(login.expiresAt).valueOf() - now) / 1000),
      )
    : 0;
  const selectedPreviewCourses = useMemo(
    () =>
      preview?.courses.filter((course) => selectedCourses.has(course.id)) ?? [],
    [preview, selectedCourses],
  );
  const job = jobDetail?.job ?? null;

  const handleDialogKeyDown = (
    event: ReactKeyboardEvent<HTMLElement>,
  ) => {
    if (event.key === "Escape") {
      event.preventDefault();
      void close();
      return;
    }
    if (event.key !== "Tab" || !dialogRef.current) return;
    const focusable = Array.from(
      dialogRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      ),
    );
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  if (!open) return null;

  return (
    <div className="capture-backdrop learning-connector-backdrop" role="presentation">
      <section
        ref={dialogRef}
        className="capture-dialog learning-connector-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="learning-connector-title"
        onKeyDown={handleDialogKeyDown}
      >
        <header className="capture-header learning-connector-header">
          <div>
            <span className="eyebrow">LEARNING PLATFORM CONNECTOR</span>
            <h2 id="learning-connector-title">从学习通导入课程资料</h2>
            <p>使用学习通 App 扫码授权。知序不会获取或保存你的学习通密码。</p>
          </div>
          <button
            className="capture-close"
            aria-label="关闭学习通导入"
            onClick={() => void close()}
            disabled={Boolean(busy)}
            type="button"
          >
            <X size={19} />
          </button>
        </header>

        <div className="learning-privacy-note">
          <ShieldCheck size={18} />
          <span>
            仅导入本人可见课程；会话最多保留 24 小时，可随时断开。
          </span>
        </div>

        {notice ? (
          <div className="knowledge-notice" role="status">
            {notice}
          </div>
        ) : null}
        {error ? (
          <div className="error-panel learning-connector-error" role="alert">
            <AlertCircle size={18} />
            <p>{error}</p>
          </div>
        ) : null}
        <input
          ref={zipInputRef}
          className="learning-hidden-file-input"
          aria-label="选择 ZIP 资料包"
          type="file"
          accept=".zip,application/zip"
          onChange={(event) => void uploadZip(event)}
        />

        {phase === "loading" ? (
          <div className="loading-panel">
            <LoaderCircle className="spin" size={20} />
            正在检查学习通连接状态
          </div>
        ) : null}

        {phase === "disabled" ? (
          <div className="learning-state-card">
            <span className="learning-state-icon">
              <Unplug size={30} />
            </span>
            <h3>学习通在线连接未开启</h3>
            <p>
              在线扫码需要服务器开启学习通连接器并配置加密密钥。
              不影响使用：把学习通的课程资料下载成 ZIP 压缩包，同样可以导入知识库。
            </p>
            <ol className="learning-zip-steps">
              <li>在学习通里打开课程，把要用的文档下载到电脑</li>
              <li>按课程建文件夹，把文档放进去，整体压缩成 ZIP</li>
              <li>点下面的按钮选择这个 ZIP，预览后即可导入</li>
            </ol>
            <button
              className="primary-button"
              onClick={() => zipInputRef.current?.click()}
              disabled={Boolean(busy)}
              type="button"
            >
              {busy === "zip" ? (
                <LoaderCircle className="spin" size={17} />
              ) : (
                <FolderInput size={17} />
              )}
              {busy === "zip" ? "正在检查资料包" : "选择 ZIP 资料包"}
            </button>
          </div>
        ) : null}

        {phase === "unreachable" ? (
          <div className="learning-state-card">
            <span className="learning-state-icon warn">
              <AlertCircle size={28} />
            </span>
            <h3>暂时读不到连接器状态</h3>
            <p>
              可能是网络中断或服务正在重启。学习通扫码依赖后端连接器，
              状态不可用时无法生成二维码。
            </p>
            {error ? (
              <p className="learning-inline-error" role="alert">
                {error}
              </p>
            ) : null}
            <div className="learning-state-actions">
              <button
                className="primary-button"
                onClick={() => void reloadStatus()}
                disabled={Boolean(busy)}
              >
                <RefreshCw size={17} />
                重新检查
              </button>
              <button
                className="secondary-button"
                onClick={() => zipInputRef.current?.click()}
                disabled={Boolean(busy)}
                type="button"
              >
                {busy === "zip" ? (
                  <LoaderCircle className="spin" size={17} />
                ) : (
                  <FolderInput size={17} />
                )}
                {busy === "zip" ? "正在检查资料包" : "改用 ZIP 资料包"}
              </button>
            </div>
          </div>
        ) : null}

        {phase === "disconnected" ? (
          <div className="learning-state-card">
            <span className="learning-state-icon">
              <QrCode size={30} />
            </span>
            <h3>邀请学习通扫码授权</h3>
            <p>
              点击生成一次性二维码，再使用学习通 App 扫码并确认登录。
            </p>
            <div className="learning-state-actions">
              <button
                className="primary-button"
                onClick={() => void startLogin()}
                disabled={Boolean(busy)}
              >
                {busy === "login" ? (
                  <LoaderCircle className="spin" size={17} />
                ) : (
                  <QrCode size={17} />
                )}
                {busy === "login" ? "正在生成二维码" : "生成学习通二维码"}
              </button>
              <button
                className="secondary-button"
                onClick={() => zipInputRef.current?.click()}
                disabled={Boolean(busy)}
                type="button"
              >
                {busy === "zip" ? (
                  <LoaderCircle className="spin" size={17} />
                ) : (
                  <FolderInput size={17} />
                )}
                {busy === "zip" ? "正在检查资料包" : "导入 ZIP 资料包"}
              </button>
            </div>
          </div>
        ) : null}

        {phase === "connected" ? (
          <div className="learning-state-card">
            <span className="learning-state-icon success">
              <Check size={28} />
            </span>
            <h3>
              {remoteNickname
                ? `已连接：${remoteNickname}`
                : "学习通连接成功"}
            </h3>
            <p>读取课程目录后可预览文件，再选择要导入的知识文件夹。</p>
            <div className="learning-state-actions">
              <button
                className="primary-button"
                onClick={() => void loadPreview()}
                disabled={Boolean(busy)}
              >
                {busy === "preview" ? (
                  <LoaderCircle className="spin" size={17} />
                ) : (
                  <FolderInput size={17} />
                )}
                {busy === "preview" ? "正在读取课程" : "读取课程资料"}
              </button>
              <button
                className="text-button"
                onClick={() => void disconnect()}
                disabled={Boolean(busy)}
              >
                {busy === "disconnect" ? (
                  <LoaderCircle className="spin" size={16} />
                ) : (
                  <Unplug size={16} />
                )}
                断开学习通
              </button>
              <button
                className="secondary-button"
                onClick={() => zipInputRef.current?.click()}
                disabled={Boolean(busy)}
                type="button"
              >
                {busy === "zip" ? (
                  <LoaderCircle className="spin" size={16} />
                ) : (
                  <FolderInput size={16} />
                )}
                导入 ZIP 资料包
              </button>
            </div>
          </div>
        ) : null}

        {phase === "qr" && login ? (
          <div className="learning-qr-layout">
            <div className="learning-qr-card">
              <img
                src={learningConnectorApi.qrUrl(login.id, login.revision)}
                alt="学习通扫码登录二维码"
                width={240}
                height={240}
              />
              <strong>
                {qrSeconds > 0
                  ? `二维码 ${Math.floor(qrSeconds / 60)
                      .toString()
                      .padStart(2, "0")}:${(qrSeconds % 60)
                      .toString()
                      .padStart(2, "0")} 后失效`
                  : "二维码已失效"}
              </strong>
            </div>
            <div className="learning-qr-instructions">
              <h3>打开学习通 App</h3>
              <ol>
                <li>点击首页右上角扫一扫</li>
                <li>扫描左侧二维码</li>
                <li>在手机上确认登录</li>
              </ol>
              <p>二维码仅绑定当前知序账号，不会在其他账号间复用。</p>
              <div className="learning-state-actions">
                <button
                  className="secondary-button"
                  onClick={() => void refreshLogin()}
                  disabled={Boolean(busy)}
                >
                  {busy === "login-refresh" ? (
                    <LoaderCircle className="spin" size={16} />
                  ) : (
                    <RefreshCw size={16} />
                  )}
                  刷新二维码
                </button>
                <button
                  className="text-button"
                  onClick={() => void pollLogin()}
                  disabled={pollingRef.current}
                >
                  {pollingRef.current ? (
                    <LoaderCircle className="spin" size={16} />
                  ) : null}
                  刷新扫码状态
                </button>
              </div>
            </div>
          </div>
        ) : null}

        {phase === "preview" && preview ? (
          <div className="learning-preview">
            <div className="learning-step-heading">
              <div>
                <span className="eyebrow">STEP 1 / COURSE PREVIEW</span>
                <h3>选择要导入的课程</h3>
                <p>
                  {preview.totalDocuments} 份文档 · {preview.totalVideoLinks}{" "}
                  个视频链接 · 预计 {formatBytes(preview.totalBytes)}
                </p>
              </div>
              <button
                className="text-button"
                onClick={toggleAll}
                type="button"
              >
                {selectedCourses.size ? "取消全选" : "全选文档"}
              </button>
            </div>
            <div className="learning-course-list">
              {preview.courses.map((course) => {
                const supportedCount = course.documents.filter(
                  (file) => file.supported,
                ).length;
                const importable =
                  supportedCount > 0 || course.videoLinks.length > 0;
                return (
                  <article
                    className="learning-course-option"
                    key={course.id}
                  >
                    <label>
                      <input
                        type="checkbox"
                        checked={selectedCourses.has(course.id)}
                        disabled={!importable}
                        onChange={() => toggleCourse(course.id)}
                      />
                      <span>
                        <strong>{course.title}</strong>
                        <small>
                          {course.teacher || "教师信息待获取"} · {supportedCount}{" "}
                          份可导入文档
                          {course.videoLinks.length
                            ? ` · ${course.videoLinks.length} 个视频链接`
                            : ""}
                        </small>
                      </span>
                    </label>
                    <details>
                      <summary>查看文件清单</summary>
                      <ul>
                        {course.documents.map((file) => (
                          <li key={file.id}>
                            <span>{file.name}</span>
                            <small>
                              {file.supported
                                ? formatBytes(file.sizeBytes)
                                : `已排除：${file.excludedReason ?? "不支持"}`}
                            </small>
                          </li>
                        ))}
                        {course.videoLinks.map((link) => (
                          <li key={link}>
                            <span>视频链接（不下载）</span>
                            <small>{link}</small>
                          </li>
                        ))}
                        {!course.documents.length &&
                        !course.videoLinks.length ? (
                          <li>
                            <span>还没有读取到资料</span>
                            <small>
                              学习通的章节要按需读取，点右侧按钮获取。
                            </small>
                          </li>
                        ) : null}
                      </ul>
                    </details>
                    <button
                      className="text-button learning-load-docs"
                      onClick={() => void loadCourseDocuments(course.id)}
                      disabled={Boolean(busy)}
                      type="button"
                    >
                      {busy === `docs:${course.id}` ? (
                        <>
                          <LoaderCircle className="spin" size={14} />
                          正在读取
                        </>
                      ) : (
                        <>
                          <RefreshCw size={14} />
                          读取资料
                        </>
                      )}
                    </button>
                  </article>
                );
              })}
            </div>
            <footer className="learning-dialog-actions">
              <button
                className="text-button"
                onClick={() => setPhase("connected")}
                type="button"
              >
                返回
              </button>
              <button
                className="primary-button"
                onClick={goToMapping}
                type="button"
              >
                下一步：设置文件夹
                <ArrowRight size={16} />
              </button>
            </footer>
          </div>
        ) : null}

        {phase === "mapping" && preview ? (
          <div className="learning-preview">
            <div className="learning-step-heading">
              <div>
                <span className="eyebrow">STEP 2 / FOLDER MAPPING</span>
                <h3>资料要放到哪里？</h3>
                <p>每门学习通课程可新建文件夹，或合并到已有文件夹。</p>
              </div>
            </div>
            <div className="learning-mapping-list">
              {selectedPreviewCourses.map((course) => {
                const mapping = mappings[course.id];
                return (
                  <div className="learning-mapping-row" key={course.id}>
                    <strong>{course.title}</strong>
                    <select
                      aria-label={`${course.title} 导入方式`}
                      value={mapping?.mode ?? "new"}
                      onChange={(event) =>
                        updateMapping(course.id, {
                          mode: event.target.value as
                            | "new"
                            | "merge"
                            | "skip",
                          targetCourseId:
                            event.target.value === "merge"
                              ? mappings[course.id]?.targetCourseId ??
                                courses[0]?.id ??
                                null
                              : mappings[course.id]?.targetCourseId,
                        })
                      }
                    >
                      <option value="new">新建文件夹</option>
                      <option value="merge" disabled={!courses.length}>
                        合并到已有文件夹
                      </option>
                      <option value="skip">暂不导入</option>
                    </select>
                    {mapping?.mode === "new" ? (
                      <input
                        aria-label={`${course.title} 新文件夹名称`}
                        value={mapping.folderTitle ?? course.title}
                        onChange={(event) =>
                          updateMapping(course.id, {
                            folderTitle: event.target.value,
                          })
                        }
                        maxLength={80}
                      />
                    ) : null}
                    {mapping?.mode === "merge" ? (
                      <select
                        aria-label={`${course.title} 目标文件夹`}
                        value={mapping.targetCourseId ?? ""}
                        onChange={(event) =>
                          updateMapping(course.id, {
                            targetCourseId: event.target.value,
                          })
                        }
                      >
                        <option value="">请选择文件夹</option>
                        {courses.map((target) => (
                          <option value={target.id} key={target.id}>
                            {target.title}
                          </option>
                        ))}
                      </select>
                    ) : null}
                  </div>
                );
              })}
            </div>
            <footer className="learning-dialog-actions">
              <button
                className="text-button"
                onClick={() => setPhase("preview")}
                type="button"
              >
                上一步
              </button>
              <button
                className="primary-button"
                onClick={() => void startImport()}
                disabled={Boolean(busy)}
                type="button"
              >
                {busy === "import" ? (
                  <LoaderCircle className="spin" size={17} />
                ) : (
                  <Check size={17} />
                )}
                {busy === "import" ? "正在创建同步任务" : "确认导入"}
              </button>
            </footer>
          </div>
        ) : null}

        {phase === "progress" && job ? (
          <div className="learning-progress">
            <div className="learning-progress-heading">
              <div>
                <span className="eyebrow">STEP 3 / BACKGROUND IMPORT</span>
                <h3>{statusLabel(job.status)}</h3>
                <p>
                  完成 {job.completedItems} · 跳过 {job.skippedItems} · 失败{" "}
                  {job.failedItems} · 共 {job.totalItems}
                </p>
              </div>
              <strong>{job.progress}%</strong>
            </div>
            <div
              className="learning-progress-bar"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={job.progress}
            >
              <span style={{ width: `${job.progress}%` }} />
            </div>

            <div className="learning-progress-list">
              {jobDetail?.items.map((item) => (
                <div
                  className={`learning-progress-item ${item.status}`}
                  key={item.id}
                >
                  <span>
                    {item.status === "completed" ? (
                      <Check size={16} />
                    ) : item.status === "failed" ? (
                      <AlertCircle size={16} />
                    ) : (
                      <LoaderCircle className="spin" size={16} />
                    )}
                    {item.title}
                  </span>
                  <small>
                    {item.errorMessage ??
                      {
                        queued: "等待处理",
                        downloading: "正在下载",
                        parsing: "正在提取知识",
                        completed: "已导入",
                        skipped: "内容未变化，已跳过",
                        failed: "导入失败",
                      }[item.status]}
                  </small>
                </div>
              ))}
            </div>

            <footer className="learning-dialog-actions">
              {isActiveJob(job) ? (
                <button
                  className="text-button"
                  onClick={() => void cancelImport()}
                  disabled={Boolean(busy)}
                >
                  {busy === "job-cancel" ? (
                    <LoaderCircle className="spin" size={16} />
                  ) : null}
                  取消同步
                </button>
              ) : job.status === "partial_failed" ||
                job.status === "session_expired" ? (
                <button
                  className="secondary-button"
                  onClick={() => void retryImport()}
                  disabled={Boolean(busy)}
                >
                  {busy === "job-retry" ? (
                    <LoaderCircle className="spin" size={16} />
                  ) : (
                    <RefreshCw size={16} />
                  )}
                  重试失败项
                </button>
              ) : (
                <span />
              )}
              <div className="learning-state-actions">
                <button
                  className="text-button"
                  onClick={() => void refreshJob(job.id)}
                  disabled={Boolean(busy)}
                >
                  {busy === "job-refresh" ? (
                    <LoaderCircle className="spin" size={16} />
                  ) : (
                    <RefreshCw size={16} />
                  )}
                  刷新进度
                </button>
                {job.status === "completed" ? (
                  <button
                    className="primary-button"
                    onClick={() => {
                      onImported();
                      onClose();
                    }}
                    type="button"
                  >
                    查看导入资料
                    <ArrowRight size={16} />
                  </button>
                ) : null}
              </div>
            </footer>
          </div>
        ) : null}
      </section>
    </div>
  );
}
