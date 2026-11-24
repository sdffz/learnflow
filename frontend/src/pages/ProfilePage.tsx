import { AlertCircle, ArrowUp, LoaderCircle, MessageSquareText, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { api } from "../api";
import ProfileRadar from "../components/ProfileRadar";
import type { Learner, ProfileUpdate } from "../types";
import type { WorkspaceTarget } from "../workspace";

interface Props {
  learner: Learner | null;
  onProfileUpdated: (update: ProfileUpdate) => void;
  onNeedLearner: () => void;
  onCreatePersonalLearner?: () => void;
  creatingPersonalLearner?: boolean;
  learnerCreationError?: string | null;
  onNavigate: (target: WorkspaceTarget) => void;
}

interface Message {
  role: "assistant" | "student";
  text: string;
}

export default function ProfilePage({
  learner,
  onProfileUpdated,
  onNeedLearner,
  onCreatePersonalLearner,
  creatingPersonalLearner = false,
  learnerCreationError = null,
  onNavigate,
}: Props) {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      text: "告诉我你正在学的课程、目标、已有基础和喜欢的学习方式。我会边聊边更新画像，不需要填长表单。",
    },
  ]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!learner) {
    return (
      <div className="empty-page">
        <MessageSquareText size={28} />
        <h2>建立你的个人学习画像</h2>
        <p>
          通过一段简短对话记录基础、目标、薄弱点和偏好，不需要填写长表单。
        </p>
        {learnerCreationError ? (
          <p className="inline-error">
            <AlertCircle size={15} />
            {learnerCreationError}
          </p>
        ) : null}
        <button
          className="primary-button"
          disabled={creatingPersonalLearner}
          onClick={onCreatePersonalLearner ?? onNeedLearner}
        >
          {creatingPersonalLearner ? (
            <LoaderCircle className="spin" size={17} />
          ) : null}
          {creatingPersonalLearner ? "正在建立画像" : "建立我的学习画像"}
        </button>
      </div>
    );
  }

  const send = async () => {
    const message = draft.trim();
    if (!message || sending) return;
    setDraft("");
    setError(null);
    setSending(true);
    setMessages((current) => [...current, { role: "student", text: message }]);
    try {
      const update = await api.chatProfile(learner.id, message);
      onProfileUpdated(update);
      setMessages((current) => [
        ...current,
        { role: "assistant", text: update.assistant_message },
      ]);
    } catch (caught) {
      setDraft(message);
      setMessages((current) => current.slice(0, -1));
      setError(caught instanceof Error ? caught.message : "画像更新失败");
    } finally {
      setSending(false);
    }
  };

  const dimensions = Object.entries(learner.profile.dimensions);

  return (
    <div className="profile-layout">
      <section className="chat-panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">PROFILE INTERVIEW</span>
            <h2>让系统先认识你</h2>
          </div>
          <span className="soft-badge">{dimensions.length} / 8 维画像</span>
        </div>

        <div className="chat-log" role="log" aria-live="polite">
          {messages.map((message, index) => (
            <div className={`chat-message ${message.role}`} key={`${message.role}-${index}`}>
              <span>{message.role === "assistant" ? "知序" : learner.name}</span>
              <p>{message.text}</p>
            </div>
          ))}
          {sending ? (
            <div className="chat-message assistant">
              <span>知序</span>
              <p className="typing-line">
                <LoaderCircle className="spin" size={15} />
                正在提取画像证据
              </p>
            </div>
          ) : null}
        </div>

        {error ? (
          <p className="inline-error">
            <AlertCircle size={15} />
            {error}
          </p>
        ) : null}

        <div className="chat-composer">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) send();
            }}
            placeholder="描述你的学习情况"
            rows={3}
          />
          <div className="composer-footer">
            <span>⌘ / Ctrl + Enter 发送</span>
            <button
              className="send-button"
              aria-label="发送"
              disabled={!draft.trim() || sending}
              onClick={send}
            >
              <ArrowUp size={18} />
            </button>
          </div>
        </div>

        {dimensions.length >= 6 ? (
          <div className="profile-next-action">
            <div>
              <strong>画像信息已足够</strong>
              <span>用当前画像生成一套个性化学习资源。</span>
            </div>
            <button className="primary-button" onClick={() => onNavigate("studio")}>
              用画像生成资源
            </button>
          </div>
        ) : null}
      </section>

      <aside className="profile-side">
        <div className="radar-card">
          <div className="mini-heading">
            <div>
              <span className="eyebrow">LEARNING COORDINATES</span>
              <h3>学习坐标</h3>
            </div>
            <ShieldCheck size={19} />
          </div>
          <ProfileRadar profile={learner.profile} />
        </div>

        <div className="dimension-list">
          {dimensions.map(([name, dimension]) => (
            <article key={name}>
              <div>
                <strong>{name}</strong>
                <span>{Math.round(dimension.confidence * 100)}% 置信度</span>
              </div>
              <p>{dimension.value}</p>
              <small>依据：{dimension.evidence}</small>
            </article>
          ))}
        </div>
      </aside>
    </div>
  );
}
