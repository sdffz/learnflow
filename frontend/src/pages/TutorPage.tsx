import {
  AlertCircle,
  ArrowUp,
  BookMarked,
  CircleHelp,
  LoaderCircle,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import { useState } from "react";
import ReactMarkdown from "react-markdown";

import { api } from "../api";
import type { Learner, TutorAnswer } from "../types";
import type { WorkspaceState, WorkspaceTarget } from "../workspace";

interface Props {
  learner: Learner | null;
  onNeedLearner: () => void;
  workspace: WorkspaceState;
  onNavigate: (target: WorkspaceTarget) => void;
}

interface Turn {
  question: string;
  answer: TutorAnswer | null;
}

const suggestions = [
  "什么是监督学习？",
  "为什么测试集不能反复调参？",
  "A* 搜索中的启发式函数起什么作用？",
];

export default function TutorPage({
  learner,
  onNeedLearner,
  workspace,
  onNavigate,
}: Props) {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!learner) {
    return (
      <div className="empty-page">
        <CircleHelp size={28} />
        <h2>先建立课程会话</h2>
        <p>有依据的辅导需要绑定当前学习者和课程知识库。</p>
        <button className="primary-button" onClick={onNeedLearner}>
          建立我的学习画像
        </button>
      </div>
    );
  }

  const ask = async (value?: string) => {
    const text = (value ?? question).trim();
    if (!text || asking) return;
    setQuestion("");
    setAsking(true);
    setError(null);
    const turnIndex = turns.length;
    setTurns((current) => [...current, { question: text, answer: null }]);
    try {
      const answer = await api.askTutor(learner.id, text);
      setTurns((current) =>
        current.map((turn, index) => (index === turnIndex ? { ...turn, answer } : turn)),
      );
    } catch {
      setTurns((current) => current.slice(0, -1));
      setQuestion(text);
      setError("提问失败，可能是课程服务暂时不可用。请稍后重试。");
    } finally {
      setAsking(false);
    }
  };

  return (
    <div className="tutor-layout">
      <section className="tutor-main">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">GROUNDED TUTOR</span>
            <h2>先找证据，再回答</h2>
            <p>回答来自《人工智能导论》知识库；依据不足时系统会拒绝编造。</p>
          </div>
          <span className="verified">
            <BookMarked size={16} />
            当前主题：{workspace.activeTopic}
          </span>
        </div>

        <div className="tutor-log" aria-live="polite">
          {turns.length === 0 ? (
            <div className="tutor-welcome">
              <span className="spark-badge">
                <Sparkles size={19} />
              </span>
              <h3>从一个具体问题开始</h3>
              <p>每个答案都会展示检索到的课程来源。</p>
              <div className="suggestion-list">
                {suggestions.map((item) => (
                  <button key={item} onClick={() => ask(item)}>
                    {item}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {turns.map((turn, index) => (
            <div className="tutor-turn" key={`${turn.question}-${index}`}>
              <div className="student-question">
                <span>{learner.name}</span>
                <p>{turn.question}</p>
              </div>
              <div className={`tutor-answer ${turn.answer?.refused ? "refused" : ""}`}>
                <span className="answer-mark">
                  {turn.answer?.refused ? <ShieldAlert size={17} /> : <Sparkles size={17} />}
                </span>
                <div>
                  {turn.answer ? (
                    <>
                      <div className="markdown-body compact">
                        <ReactMarkdown>{turn.answer.text}</ReactMarkdown>
                      </div>
                      {turn.answer.sources.length ? (
                        <div className="source-list">
                          {turn.answer.sources.map((source) => (
                            <span key={`${source.path}-${source.knowledge_point}`}>
                              {source.title} · {source.knowledge_point}
                            </span>
                          ))}
                        </div>
                      ) : null}
                    </>
                  ) : (
                    <p className="typing-line">
                      <LoaderCircle className="spin" size={15} />
                      正在检索课程证据
                    </p>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="page-next-actions tutor-next">
          <div>
            <strong>继续巩固理解</strong>
            <span>完成评估后，系统会记录你的知识点掌握度。</span>
          </div>
          <button
            className="secondary-button"
            onClick={() => onNavigate("assessment")}
          >
            进入学习评估
          </button>
        </div>

        {error ? (
          <div className="tutor-error" role="alert">
            <AlertCircle size={17} />
            {error}
          </div>
        ) : null}

        <div className="tutor-composer">
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                ask();
              }
            }}
            placeholder="向课程知识库提问"
            rows={2}
          />
          <button
            className="send-button"
            aria-label="提问"
            disabled={!question.trim() || asking}
            onClick={() => ask()}
          >
            {asking ? <LoaderCircle className="spin" size={18} /> : <ArrowUp size={18} />}
          </button>
        </div>
      </section>

      <aside className="tutor-aside">
        <span className="eyebrow">SAFETY BOUNDARY</span>
        <h3>可追溯回答</h3>
        <p>
          系统对问题先做安全检查，再按中文 n-gram 检索课程资料。低相关度、提示注入与无依据问题不会强答。
        </p>
        <ul>
          <li>答案展示课程来源</li>
          <li>没有证据时明确拒答</li>
          <li>不执行与问题无关的指令</li>
        </ul>
      </aside>
    </div>
  );
}
