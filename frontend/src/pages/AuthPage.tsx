import {
  AlertCircle,
  ArrowRight,
  BookOpenCheck,
  LoaderCircle,
  LockKeyhole,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useState, type FormEvent } from "react";

import { ApiError, authApi } from "../api";
import type { AuthContext } from "../types";

interface Props {
  onAuthenticated: (context: AuthContext) => void;
  initialError?: string | null;
}

type Mode = "login" | "register";

function authErrorMessage(caught: unknown): string {
  if (caught instanceof ApiError && caught.status === 401) {
    return "邮箱或密码不正确";
  }
  if (caught instanceof ApiError && caught.status === 409) {
    return "该邮箱已经注册，请直接登录";
  }
  return caught instanceof Error
    ? caught.message
    : "暂时无法连接账号服务，请稍后重试";
}

export default function AuthPage({
  onAuthenticated,
  initialError = null,
}: Props) {
  const [mode, setMode] = useState<Mode>("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const switchMode = (nextMode: Mode) => {
    setMode(nextMode);
    setError(null);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setError(null);
    if (
      mode === "register" &&
      password !== confirmPassword
    ) {
      setError("两次输入的密码不一致");
      return;
    }
    if (
      mode === "register" &&
      (password.length < 10 || password.length > 128)
    ) {
      setError("密码长度应为 10 到 128 个字符");
      return;
    }

    setBusy(true);
    try {
      const context =
        mode === "login"
          ? await authApi.login(email.trim(), password)
          : await authApi.register(name.trim(), email.trim(), password);
      onAuthenticated(context);
    } catch (caught) {
      setError(authErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="auth-shell">
      <section className="auth-story">
        <div className="auth-brand">
          <span className="brand-mark">
            <BookOpenCheck size={25} strokeWidth={1.8} />
          </span>
          <div>
            <strong>知序 LearnFlow</strong>
            <small>个人知识管理与学习智能体</small>
          </div>
        </div>
        <div className="auth-story-copy">
          <span className="eyebrow">PRIVATE KNOWLEDGE WORKSPACE</span>
          <h1>让你的资料，真正成为自己的学习系统。</h1>
          <p>
            每个账号拥有独立知识文件夹。课程资料、照片、笔记和生成内容只在当前工作空间内可见。
          </p>
        </div>
        <div className="auth-trust-list">
          <div>
            <ShieldCheck size={18} />
            <span>会话使用 HttpOnly Cookie</span>
          </div>
          <div>
            <LockKeyhole size={18} />
            <span>资料按用户工作空间隔离</span>
          </div>
          <div>
            <Sparkles size={18} />
            <span>智能体只使用你选择的资料</span>
          </div>
        </div>
      </section>

      <section className="auth-panel">
        <div className="auth-panel-header">
          <span className="eyebrow">
            {mode === "login" ? "WELCOME BACK" : "CREATE WORKSPACE"}
          </span>
          <h2>{mode === "login" ? "登录你的知识空间" : "创建个人账号"}</h2>
          <p>
            {mode === "login"
              ? "继续整理资料、生成资源并跟踪学习进度。"
              : "首次注册会建立独立的知识空间和启动文件夹。"}
          </p>
        </div>

        <form className="auth-form" onSubmit={submit}>
          {mode === "register" ? (
            <label>
              姓名
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                autoComplete="name"
                required
                maxLength={80}
              />
            </label>
          ) : null}
          <label>
            邮箱
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
              required
              maxLength={254}
            />
          </label>
          <label>
            密码
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete={
                mode === "login" ? "current-password" : "new-password"
              }
              required
              minLength={mode === "register" ? 10 : 1}
              maxLength={128}
            />
          </label>
          {mode === "register" ? (
            <>
              <label>
                确认密码
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  autoComplete="new-password"
                  required
                  minLength={10}
                  maxLength={128}
                />
              </label>
            </>
          ) : null}

          {error ?? initialError ? (
            <div className="auth-error" role="alert">
              <AlertCircle size={17} />
              {error ?? initialError}
            </div>
          ) : null}

          <button
            className="primary-button auth-submit"
            type="submit"
            disabled={
              busy ||
              !email.trim() ||
              !password ||
              (mode === "register" && !name.trim())
            }
          >
            {busy ? (
              <LoaderCircle className="spin" size={17} />
            ) : null}
            {busy
              ? "正在验证"
              : mode === "login"
                ? "登录"
                : "注册并进入"}
            {!busy ? <ArrowRight size={16} /> : null}
          </button>
        </form>

        <button
          className="auth-switch"
          type="button"
          aria-label={mode === "login" ? "创建账号" : "返回登录"}
          onClick={() =>
            switchMode(mode === "login" ? "register" : "login")
          }
        >
          {mode === "login"
            ? "没有账号？创建账号"
            : "已有账号？返回登录"}
        </button>
      </section>
    </main>
  );
}
