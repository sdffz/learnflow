import {
  AlertCircle,
  Check,
  ChartNoAxesCombined,
  LoaderCircle,
  RefreshCw,
  RotateCcw,
  Sparkles,
} from "lucide-react";
import { useCallback, useEffect, useState, type CSSProperties } from "react";

import { api } from "../api";
import type {
  AssessmentQuestion,
  AssessmentResult,
  Learner,
  LearnerProfile,
} from "../types";
import type { WorkspaceTarget } from "../workspace";

interface Props {
  learner: Learner | null;
  onNeedLearner: () => void;
  onProfileUpdated: (profile: LearnerProfile) => void;
  onAssessmentComplete: (score: number) => void;
  onNavigate: (target: WorkspaceTarget) => void;
}

export default function AssessmentPage({
  learner,
  onNeedLearner,
  onProfileUpdated,
  onAssessmentComplete,
  onNavigate,
}: Props) {
  const [questions, setQuestions] = useState<AssessmentQuestion[]>([]);
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [result, setResult] = useState<AssessmentResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadQuestions = useCallback(async () => {
    if (!learner) return;
    setLoading(true);
    setError(null);
    try {
      const items = await api.getAssessmentQuestions();
      setQuestions(items);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "题目加载失败");
    } finally {
      setLoading(false);
    }
  }, [learner]);

  useEffect(() => {
    void loadQuestions();
  }, [loadQuestions]);

  if (!learner) {
    return (
      <div className="empty-page">
        <ChartNoAxesCombined size={28} />
        <h2>先选择一个学习者</h2>
        <p>评估结果会回写掌握度并影响后续资源推荐。</p>
        <button className="primary-button" onClick={onNeedLearner}>
          建立我的学习画像
        </button>
      </div>
    );
  }

  const answeredCount = Object.keys(answers).length;
  const remainingCount = Math.max(questions.length - answeredCount, 0);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const value = await api.submitAssessment(learner.id, answers);
      setResult(value);
      onProfileUpdated(value.updated_profile);
      onAssessmentComplete(value.score);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "评估提交失败");
    } finally {
      setSubmitting(false);
    }
  };

  if (result) {
    return (
      <div className="result-layout">
        <section className="result-hero">
          <div className="score-ring" style={{ "--score": `${result.score * 3.6}deg` } as CSSProperties}>
            <div>
              <strong>{result.score}</strong>
              <span>综合得分</span>
            </div>
          </div>
          <div>
            <span className="eyebrow">ASSESSMENT REPORT</span>
            <h2>{result.score >= 80 ? "掌握正在成形" : "找到了需要补强的位置"}</h2>
            <p>{result.recommendation}</p>
            <div className="result-actions">
              <button
                className="secondary-button"
                onClick={() => {
                  setResult(null);
                  setAnswers({});
                }}
              >
                <RotateCcw size={16} />
                再测一次
              </button>
              <button
                className="primary-button"
                onClick={() => onNavigate("home")}
              >
                返回学习工作台
              </button>
            </div>
          </div>
        </section>

        <section className="mastery-panel">
          <div className="section-heading compact-heading">
            <div>
              <span className="eyebrow">KNOWLEDGE MASTERY</span>
              <h2>知识点掌握度</h2>
            </div>
            <span className="soft-badge">
              {result.correct_count} / {result.total} 正确
            </span>
          </div>
          <div className="mastery-list">
            {Object.entries(result.mastery).map(([topic, mastery]) => (
              <div key={topic}>
                <div>
                  <strong>{topic}</strong>
                  <span>{Math.round(mastery * 100)}%</span>
                </div>
                <div className="mastery-track">
                  <span style={{ width: `${mastery * 100}%` }} />
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="page-stack">
      <section className="assessment-header">
        <div>
          <span className="eyebrow">POST-LEARNING CHECK</span>
          <h2>用五道题检查掌握，而不是猜你学会了。</h2>
          <p>提交后由后端评分，并更新画像中的知识点掌握度。</p>
        </div>
        <span className="soft-badge">
          {answeredCount} / {questions.length || 5} 已作答
        </span>
      </section>

      {loading ? (
        <div className="loading-panel">
          <LoaderCircle className="spin" size={20} />
          正在载入课程评估题
        </div>
      ) : null}

      {error ? (
        <div className="error-panel" role="alert">
          <AlertCircle size={18} />
          <p>{error}</p>
          {questions.length === 0 && !loading ? (
            <button
              className="secondary-button"
              onClick={() => void loadQuestions()}
            >
              <RefreshCw size={16} />
              重新加载题目
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="assessment-list">
        {questions.map((question, index) => (
          <article key={question.id}>
            <div className="question-meta">
              <span>QUESTION {String(index + 1).padStart(2, "0")}</span>
              <strong>{question.knowledge_point}</strong>
            </div>
            <h3>{question.stem}</h3>
            <div className="assessment-options">
              {question.options.map((option, optionIndex) => {
                const selected = answers[question.id] === optionIndex;
                return (
                  <button
                    className={selected ? "selected" : ""}
                    key={option}
                    onClick={() =>
                      setAnswers((current) => ({
                        ...current,
                        [question.id]: optionIndex,
                      }))
                    }
                  >
                    <span>{selected ? <Check size={15} /> : String.fromCharCode(65 + optionIndex)}</span>
                    {option}
                  </button>
                );
              })}
            </div>
          </article>
        ))}
      </div>

      <div className="assessment-submit">
        <div>
          <Sparkles size={17} />
          <span>
            {remainingCount > 0
              ? `还差 ${remainingCount} 题，完成后才能提交`
              : "题目已答完，提交后会更新画像与推荐"}
          </span>
        </div>
        <button
          className="primary-button"
          disabled={
            submitting ||
            questions.length === 0 ||
            answeredCount !== questions.length
          }
          onClick={submit}
        >
          {submitting ? <LoaderCircle className="spin" size={17} /> : <ChartNoAxesCombined size={17} />}
          提交并更新画像
        </button>
      </div>
    </div>
  );
}
