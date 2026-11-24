import { useState } from "react";
import { ChevronLeft, ChevronRight, Play, RotateCcw } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/* ------------------------------------------------------------------ quiz */

interface QuizQuestion {
  id: string;
  stem: string;
  options: string[];
  answer: number;
  explanation: string;
}

/**
 * Quiz with scoring. Previously each card revealed its own answer but there
 * was no aggregate result, so a learner could not tell how they did.
 */
export function QuizView({ questions }: { questions: QuizQuestion[] }) {
  const [selected, setSelected] = useState<Record<string, number>>({});
  const answered = Object.keys(selected).length;
  const correct = questions.filter(
    (question) => selected[question.id] === question.answer,
  ).length;
  const done = answered === questions.length && questions.length > 0;

  return (
    <div className="quiz-list">
      <div className="quiz-progress">
        <div className="quiz-progress-text">
          <strong>
            {answered} / {questions.length}
          </strong>
          <span>已作答</span>
        </div>
        <div className="quiz-progress-bar" aria-hidden="true">
          <div style={{ width: `${(answered / Math.max(1, questions.length)) * 100}%` }} />
        </div>
        {answered ? (
          <span className="quiz-score">
            答对 {correct} 题
          </span>
        ) : null}
        {answered ? (
          <button className="quiz-reset" onClick={() => setSelected({})}>
            <RotateCcw size={14} />
            重新作答
          </button>
        ) : null}
      </div>

      {done ? (
        <p className="quiz-summary" role="status">
          {correct === questions.length
            ? "全部答对。可以进入代码实验动手验证了。"
            : `答对 ${correct} / ${questions.length}，回看错题解析后再试一次。`}
        </p>
      ) : null}

      {questions.map((question, index) => {
        const chosen = selected[question.id];
        const revealed = chosen !== undefined;
        const isRight = chosen === question.answer;
        return (
          <article
            className={`quiz-card${revealed ? (isRight ? " is-right" : " is-wrong") : ""}`}
            key={question.id}
          >
            <span className="resource-kicker">
              QUESTION {String(index + 1).padStart(2, "0")}
            </span>
            <h4>{question.stem}</h4>
            <div className="quiz-options">
              {question.options.map((option, optionIndex) => {
                const picked = chosen === optionIndex;
                const correctOption = optionIndex === question.answer;
                return (
                  <button
                    key={option}
                    className={[
                      picked ? "chosen" : "",
                      revealed && correctOption ? "correct" : "",
                      revealed && picked && !correctOption ? "wrong" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    onClick={() =>
                      setSelected((current) => ({
                        ...current,
                        [question.id]: optionIndex,
                      }))
                    }
                  >
                    <span>{String.fromCharCode(65 + optionIndex)}</span>
                    {option}
                  </button>
                );
              })}
            </div>
            {revealed ? (
              <p className="quiz-explanation">
                <strong>{isRight ? "回答正确" : "再看一下"}</strong>
                {question.explanation}
              </p>
            ) : null}
          </article>
        );
      })}
    </div>
  );
}

/* ---------------------------------------------------------------- slides */

interface Slide {
  title: string;
  kicker: string;
  body: string;
}

/**
 * Paged deck. The deck used to render every slide stacked, so a seven-page
 * lesson meant scrolling through seven full screens to read it in order.
 */
export function SlidesView({ slides }: { slides: Slide[] }) {
  const [index, setIndex] = useState(0);
  const total = slides.length;
  if (!total) return <p className="slide-empty">这个课件还没有页面。</p>;
  const slide = slides[Math.min(index, total - 1)];

  return (
    <div className="slide-viewer">
      <article className="lesson-slide" aria-live="polite">
        <span>{slide.kicker}</span>
        <h4>{slide.title}</h4>
        <p>{slide.body}</p>
      </article>

      <div className="slide-controls">
        <button
          onClick={() => setIndex((current) => Math.max(0, current - 1))}
          disabled={index === 0}
          aria-label="上一页"
        >
          <ChevronLeft size={16} />
        </button>
        <div className="slide-dots" role="tablist" aria-label="课件页面">
          {slides.map((item, dotIndex) => (
            <button
              key={`${item.title}-${dotIndex}`}
              role="tab"
              aria-selected={dotIndex === index}
              aria-label={`第 ${dotIndex + 1} 页：${item.title}`}
              className={dotIndex === index ? "active" : ""}
              onClick={() => setIndex(dotIndex)}
            />
          ))}
        </div>
        <button
          onClick={() => setIndex((current) => Math.min(total - 1, current + 1))}
          disabled={index === total - 1}
          aria-label="下一页"
        >
          <ChevronRight size={16} />
        </button>
        <span className="slide-counter">
          {index + 1} / {total}
        </span>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- codelab */

interface CodelabProps {
  task: string;
  starter: string;
  solution: string;
  expectedOutput: string;
  explanation: string;
  language: string;
}

/**
 * Code lab that hides the reference solution until asked for, and lets the
 * learner copy either block. The solution used to sit open next to the starter,
 * which removed the point of the exercise.
 */
export function CodelabView({
  task,
  starter,
  solution,
  expectedOutput,
  explanation,
  language,
}: CodelabProps) {
  const [showSolution, setShowSolution] = useState(false);
  const [copied, setCopied] = useState<"starter" | "solution" | null>(null);

  const copy = async (kind: "starter" | "solution", text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(kind);
      window.setTimeout(() => setCopied(null), 1500);
    } catch {
      setCopied(null);
    }
  };

  return (
    <div className="codelab">
      {/* Model-authored task text contains markdown emphasis and lists. */}
      <div className="codelab-task markdown-body">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{task}</ReactMarkdown>
      </div>

      <div className="code-block">
        <div className="code-block-head">
          <span className="code-label">STARTER · {language}</span>
          <button onClick={() => copy("starter", starter)}>
            {copied === "starter" ? "已复制" : "复制"}
          </button>
        </div>
        <pre>{starter}</pre>
      </div>

      <div className="codelab-actions">
        <button
          className="codelab-toggle"
          onClick={() => setShowSolution((value) => !value)}
          aria-expanded={showSolution}
        >
          {showSolution ? "隐藏参考答案" : "卡住了？看参考答案"}
        </button>
        {expectedOutput ? (
          <span className="code-output">
            预期输出 <code>{expectedOutput}</code>
          </span>
        ) : null}
      </div>

      {showSolution ? (
        <div className="code-block">
          <div className="code-block-head">
            <span className="code-label">REFERENCE</span>
            <button onClick={() => copy("solution", solution)}>
              {copied === "solution" ? "已复制" : "复制"}
            </button>
          </div>
          <pre>{solution}</pre>
        </div>
      ) : null}

      {explanation ? <p className="codelab-explanation">{explanation}</p> : null}
    </div>
  );
}

/* ------------------------------------------------------------- animation */

/**
 * Animation runner. The iframe has always been an animated page, but there was
 * no way to replay it once it finished.
 */
export function AnimationView({ html, title }: { html: string; title: string }) {
  const [runId, setRunId] = useState(0);
  const [started, setStarted] = useState(false);

  return (
    <div className="animation-viewer">
      <div className="animation-frame-wrap">
        {started ? (
          <iframe
            key={runId}
            className="animation-frame"
            title={title}
            sandbox="allow-scripts"
            srcDoc={html}
          />
        ) : (
          <button className="animation-launch" onClick={() => setStarted(true)}>
            <Play size={26} />
            <strong>播放动画微课</strong>
            <span>按步骤展示整个过程</span>
          </button>
        )}
      </div>
      {started ? (
        <div className="animation-controls">
          <button onClick={() => setRunId((value) => value + 1)}>
            <RotateCcw size={15} />
            重新播放
          </button>
        </div>
      ) : null}
    </div>
  );
}
