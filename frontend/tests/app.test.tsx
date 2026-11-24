import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import App from "../src/App";
import type {
  AuthContext,
  Course,
  KnowledgeAsset,
  KnowledgeOverview,
  Learner,
} from "../src/types";

const course: Course = {
  id: "course-1",
  title: "数据结构",
  description: "树、图与算法",
  color: "#e25d3f",
  assetCount: 1,
  knowledgeCount: 2,
  updatedAt: "2026-11-21T08:00:00Z",
};

const asset: KnowledgeAsset = {
  id: "asset-1",
  courseId: course.id,
  courseTitle: course.title,
  kind: "note",
  title: "BFS 队列",
  originalName: null,
  mimeType: null,
  status: "ready",
  summary: "广度优先搜索使用队列。",
  content: "广度优先搜索使用队列。",
  tags: ["图论"],
  knowledgeCount: 1,
  error: null,
  createdAt: "2026-11-21T08:00:00Z",
  updatedAt: "2026-11-21T08:00:00Z",
};

const overview: KnowledgeOverview = {
  courseCount: 1,
  assetCount: 1,
  knowledgeCount: 2,
  pendingCount: 0,
  recentAssets: [asset],
  courses: [course],
  topTags: ["图论"],
};

const personalLearner: Learner = {
  id: "learner-1",
  name: "我的学习空间",
  course_id: "ai-intro",
  persona_id: null,
  profile: { dimensions: {}, mastery: {} },
};

const authContext: AuthContext = {
  user: { id: "user-1", name: "林同学", email: "student@example.com" },
  workspace: {
    id: "workspace-1",
    name: "林同学的知识空间",
    role: "owner",
  },
};

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function installApi(
  nextOverview: KnowledgeOverview = overview,
  nextCourses: Course[] = [course],
) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return response(authContext);
      if (url.endsWith("/auth/logout") && init?.method === "POST") {
        return new Response(null, { status: 204 });
      }
      if (url.includes("/knowledge/overview")) return response(nextOverview);
      if (url.endsWith("/courses") && (!init?.method || init.method === "GET")) {
        return response({ items: nextCourses });
      }
      if (url.includes(`/courses/${course.id}/assets`)) {
        return response({ items: [asset] });
      }
      if (
        url.includes("/knowledge/search") &&
        url.includes(`courseId=${course.id}`)
      ) {
        return response({
          items: [
            {
              id: "chunk-1",
              assetId: asset.id,
              assetTitle: asset.title,
              courseId: course.id,
              courseTitle: course.title,
              title: "广度优先搜索",
              excerpt: "广度优先搜索使用队列。",
              tags: ["图论"],
            },
          ],
        });
      }
      if (url.endsWith("/learners") && init?.method === "POST") {
        return response(personalLearner, 201);
      }
      return response({ detail: `unexpected_request: ${url}` }, 404);
    }),
  );
}

afterEach(() => {
  window.localStorage.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("app opens on the personal knowledge workspace", async () => {
  installApi();
  render(<App />);

  expect(await screen.findByText("个人知识工作台")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "知识文件夹" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "知识库" })).toBeInTheDocument();
  expect(
    screen.queryByText("选择一位演示学生"),
  ).not.toBeInTheDocument();
});

test("anonymous visitor is required to sign in", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      response({ detail: "authentication_required" }, 401),
    ),
  );
  render(<App />);

  expect(await screen.findByText("登录你的知识空间")).toBeInTheDocument();
  expect(screen.getByLabelText("邮箱")).toBeInTheDocument();
  expect(screen.getByLabelText("密码")).toBeInTheDocument();
  expect(screen.queryByText("个人知识工作台")).not.toBeInTheDocument();
});

test("authenticated user can sign out", async () => {
  installApi();
  render(<App />);

  fireEvent.click(
    await screen.findByRole("button", { name: "退出登录" }),
  );

  expect(await screen.findByText("登录你的知识空间")).toBeInTheDocument();
});

test("dashboard can open a course without selecting a demo student", async () => {
  installApi();
  render(<App />);

  fireEvent.click(
    await screen.findByRole("button", { name: /数据结构.*份资料/ }),
  );

  expect(await screen.findByText("文件夹资料")).toBeInTheDocument();
  expect(screen.getByText("BFS 队列")).toBeInTheDocument();
  expect(screen.queryByText("先选择一位演示学生")).not.toBeInTheDocument();
});

test("global capture button opens the personal knowledge composer", async () => {
  installApi();
  render(<App />);

  fireEvent.click(
    await screen.findByRole("button", { name: "打开添加知识" }),
  );

  expect(screen.getByRole("dialog", { name: "添加知识" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "快速笔记" })).toBeInTheDocument();
});

test("profile page can create a personal learner", async () => {
  installApi();
  render(<App />);

  fireEvent.click(
    await screen.findByRole("button", { name: "学习画像" }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "建立我的学习画像" }),
  );

  await waitFor(() => {
    expect(screen.getByText("让系统先认识你")).toBeInTheDocument();
  });
});

test("learner-dependent pages guide the user to create a personal profile", async () => {
  installApi();
  render(<App />);

  fireEvent.click(
    await screen.findByRole("button", { name: "智能生成" }),
  );

  expect(
    screen.getByRole("button", { name: "建立我的学习画像" }),
  ).toBeInTheDocument();
});

test("empty dashboard create action opens the course form directly", async () => {
  installApi(
    {
      courseCount: 0,
      assetCount: 0,
      knowledgeCount: 0,
      pendingCount: 0,
      recentAssets: [],
      courses: [],
      topTags: [],
    },
    [],
  );
  render(<App />);

  fireEvent.click(await screen.findByRole("button", { name: "创建第一个文件夹" }));

  expect(await screen.findByText("创建知识文件夹")).toBeInTheDocument();
  expect(
    screen.getByPlaceholderText("例如：数据结构、考研英语、课堂重点"),
  ).toBeInTheDocument();
});
