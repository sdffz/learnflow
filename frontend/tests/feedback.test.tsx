import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import ResourcePanel from "../src/components/ResourcePanel";
import AssessmentPage from "../src/pages/AssessmentPage";
import PathPage from "../src/pages/PathPage";
import ProfilePage from "../src/pages/ProfilePage";
import StudioPage from "../src/pages/StudioPage";
import TutorPage from "../src/pages/TutorPage";
import type { Course, Learner, LearningResource } from "../src/types";
import { createDefaultWorkspace } from "../src/workspace";

const learner: Learner = {
  id: "learner-1",
  name: "测试学生",
  course_id: "ai-intro",
  persona_id: "beginner",
  profile: { dimensions: {}, mastery: {} },
};

const course: Course = {
  id: "course-1",
  title: "人工智能导论",
  description: "AI 基础",
  color: "#e25d3f",
  assetCount: 1,
  knowledgeCount: 2,
  updatedAt: "2026-11-21T10:00:00Z",
};

const documentResource: LearningResource = {
  id: "resource-1",
  type: "document",
  title: "监督学习讲解",
  knowledge_point: "监督学习",
  content: { markdown: "# 监督学习" },
  metadata: {},
  status: "verified",
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("tutor request failure shows a visible retryable error", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "tutor_unavailable" }), {
        status: 503,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  render(
    <TutorPage
      learner={learner}
      onNeedLearner={() => undefined}
      workspace={createDefaultWorkspace()}
      onNavigate={() => undefined}
    />,
  );

  fireEvent.change(screen.getByPlaceholderText("向课程知识库提问"), {
    target: { value: "什么是监督学习？" },
  });
  fireEvent.click(screen.getByRole("button", { name: "提问" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(/提问失败/);
});

test("successful resource download reports that it started", async () => {
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response("download body", {
        status: 200,
        headers: {
          "Content-Type": "text/markdown",
          "Content-Disposition": "attachment; filename=lesson.md",
        },
      }),
    ),
  );
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: vi.fn(() => "blob:test"),
    revokeObjectURL: vi.fn(),
  });
  render(<ResourcePanel resources={[documentResource]} />);

  fireEvent.click(screen.getByRole("button", { name: "下载" }));

  expect(await screen.findByRole("status")).toHaveTextContent("已开始下载");
});

test("failed resource download shows an error instead of silently stopping", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response("denied", { status: 500 })),
  );
  render(<ResourcePanel resources={[documentResource]} />);

  fireEvent.click(screen.getByRole("button", { name: "下载" }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent("下载失败");
  });
});

test("changing the studio topic writes it to shared workspace state", () => {
  const onWorkspaceChange = vi.fn();
  render(
    <StudioPage
      learner={learner}
      onNeedLearner={() => undefined}
      workspace={createDefaultWorkspace()}
      onWorkspaceChange={onWorkspaceChange}
      onNavigate={() => undefined}
      courses={[course]}
    />,
  );

  fireEvent.change(screen.getByLabelText("学习主题"), {
    target: { value: "机器学习" },
  });

  expect(onWorkspaceChange).toHaveBeenCalledWith({ activeTopic: "机器学习" });
});

test("failed resource generation turns the primary action into a retry", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "generation_unavailable" }), {
        status: 503,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  render(
    <StudioPage
      learner={learner}
      onNeedLearner={() => undefined}
      workspace={{ ...createDefaultWorkspace(), activeTopic: "机器学习" }}
      onWorkspaceChange={() => undefined}
      onNavigate={() => undefined}
      courses={[course]}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "生成六类资源" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    /generation_unavailable/,
  );
  expect(
    screen.getByRole("button", { name: "重试生成六类资源" }),
  ).toBeEnabled();
});

test("failed profile message is removed and restored to the composer", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "profile_unavailable" }), {
        status: 503,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  render(
    <ProfilePage
      learner={learner}
      onProfileUpdated={() => undefined}
      onNeedLearner={() => undefined}
      onNavigate={() => undefined}
    />,
  );

  const message = "我喜欢视频，每周学习六小时。";
  fireEvent.change(screen.getByPlaceholderText("描述你的学习情况"), {
    target: { value: message },
  });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));

  expect(await screen.findByText(/profile_unavailable/)).toBeInTheDocument();
  expect(screen.getByPlaceholderText("描述你的学习情况")).toHaveValue(message);
  expect(within(screen.getByRole("log")).queryByText(message)).not.toBeInTheDocument();
});

test("failed path generation offers a working retry", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "path_unavailable" }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "path-1",
            learner_id: learner.id,
            title: "重新生成的路径",
            adjustment_note: "已恢复",
            nodes: [],
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
      ),
  );

  render(
    <PathPage
      learner={learner}
      onNeedLearner={() => undefined}
      onWorkspaceChange={() => undefined}
      onNavigate={() => undefined}
    />,
  );

  expect(await screen.findByRole("alert")).toHaveTextContent(/path_unavailable/);
  fireEvent.click(screen.getByRole("button", { name: "重新生成路径" }));

  expect(await screen.findByText("重新生成的路径")).toBeInTheDocument();
});

test("assessment explains how many questions are still unanswered", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          questions: [
            {
              id: "q1",
              stem: "题目一",
              options: ["A", "B"],
              knowledge_point: "知识点一",
              explanation: "",
            },
            {
              id: "q2",
              stem: "题目二",
              options: ["A", "B"],
              knowledge_point: "知识点二",
              explanation: "",
            },
          ],
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    ),
  );

  render(
    <AssessmentPage
      learner={learner}
      onNeedLearner={() => undefined}
      onProfileUpdated={() => undefined}
      onAssessmentComplete={() => undefined}
      onNavigate={() => undefined}
    />,
  );

  const firstQuestion = (
    await screen.findByRole("heading", { name: "题目一" })
  ).closest("article");
  expect(firstQuestion).not.toBeNull();
  fireEvent.click(within(firstQuestion!).getByRole("button", { name: "AA" }));

  expect(screen.getByText("还差 1 题，完成后才能提交")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "提交并更新画像" }),
  ).toBeDisabled();
});

test("failed assessment loading offers a working reload", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "questions_unavailable" }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            questions: [
              {
                id: "q1",
                stem: "恢复后的题目",
                options: ["A", "B"],
                knowledge_point: "知识点",
                explanation: "",
              },
            ],
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
      ),
  );

  render(
    <AssessmentPage
      learner={learner}
      onNeedLearner={() => undefined}
      onProfileUpdated={() => undefined}
      onAssessmentComplete={() => undefined}
      onNavigate={() => undefined}
    />,
  );

  expect(await screen.findByRole("alert")).toHaveTextContent(
    /questions_unavailable/,
  );
  fireEvent.click(screen.getByRole("button", { name: "重新加载题目" }));

  expect(await screen.findByText("恢复后的题目")).toBeInTheDocument();
});
