import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import AssetDetailPage from "../src/pages/AssetDetailPage";
import KnowledgeDashboardPage from "../src/pages/KnowledgeDashboardPage";
import KnowledgePage from "../src/pages/KnowledgePage";
import type {
  AssetDetail,
  KnowledgeChunk,
  KnowledgeOverview,
} from "../src/types";

const overview: KnowledgeOverview = {
  courseCount: 2,
  assetCount: 5,
  knowledgeCount: 18,
  pendingCount: 1,
  recentAssets: [],
  courses: [],
  topTags: ["图论", "机器学习"],
};

const chunk: KnowledgeChunk = {
  id: "chunk-1",
  assetId: "asset-1",
  assetTitle: "BFS 课堂笔记",
  courseId: "course-1",
  courseTitle: "算法",
  title: "广度优先搜索",
  excerpt: "广度优先搜索使用队列，逐层访问节点。",
  tags: ["图论", "搜索"],
};

const asset: AssetDetail = {
  id: "asset-1",
  courseId: "course-1",
  courseTitle: "算法",
  kind: "file",
  title: "BFS 课堂笔记",
  originalName: "bfs.md",
  mimeType: "text/markdown",
  status: "ready",
  summary: "广度优先搜索使用队列，逐层访问节点。",
  content: "广度优先搜索使用队列，逐层访问节点。",
  tags: ["图论", "搜索"],
  knowledgeCount: 1,
  error: null,
  createdAt: "2026-11-21T10:00:00Z",
  updatedAt: "2026-11-21T10:00:00Z",
  chunks: [chunk],
  fileAvailable: true,
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("empty dashboard asks the user to create a first course", () => {
  render(
    <KnowledgeDashboardPage
      overview={{
        ...overview,
        courseCount: 0,
        assetCount: 0,
        knowledgeCount: 0,
        pendingCount: 0,
      }}
      onCapture={vi.fn()}
      onOpenCourse={vi.fn()}
      onOpenAsset={vi.fn()}
      onOpenKnowledge={vi.fn()}
      onCreateCourse={vi.fn()}
    />,
  );

  expect(screen.getByText("创建你的第一个知识文件夹")).toBeInTheDocument();
});

test("dashboard shows personal knowledge totals and recent captures", () => {
  render(
    <KnowledgeDashboardPage
      overview={{ ...overview, recentAssets: [asset] }}
      onCapture={vi.fn()}
      onOpenCourse={vi.fn()}
      onOpenAsset={vi.fn()}
      onOpenKnowledge={vi.fn()}
      onCreateCourse={vi.fn()}
    />,
  );

  expect(screen.getByText("个人知识工作台")).toBeInTheDocument();
  expect(screen.getByText("18")).toBeInTheDocument();
  expect(screen.getByText("BFS 课堂笔记")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "添加知识" })).toBeInTheDocument();
});

test("knowledge search keeps course and asset source with each hit", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [chunk] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  render(<KnowledgePage tags={["图论"]} onOpenAsset={vi.fn()} />);

  fireEvent.change(
    screen.getByPlaceholderText("搜索文件夹、资料、标签或正文"),
    { target: { value: "队列" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "搜索" }));

  expect(await screen.findByText("算法 · BFS 课堂笔记")).toBeInTheDocument();
  expect(
    screen.getByText("广度优先搜索使用队列，逐层访问节点。"),
  ).toBeInTheDocument();
});

test("knowledge search explains when nothing matches", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  render(<KnowledgePage tags={[]} onOpenAsset={vi.fn()} />);

  fireEvent.change(
    screen.getByPlaceholderText("搜索文件夹、资料、标签或正文"),
    { target: { value: "不存在" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "搜索" }));

  expect(
    await screen.findByText("没有找到匹配内容，试试更短的关键词或更换标签。"),
  ).toBeInTheDocument();
});

test("asset detail fetches and shows original content plus extracted chunks", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(asset), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  render(<AssetDetailPage assetId={asset.id} onBack={vi.fn()} />);

  expect(await screen.findByText("BFS 课堂笔记")).toBeInTheDocument();
  expect(
    screen.getAllByText("广度优先搜索使用队列，逐层访问节点。").length,
  ).toBeGreaterThan(0);
  expect(
    screen.getByRole("link", { name: "打开原始文件" }).getAttribute("href"),
  ).toMatch(/\/api\/assets\/asset-1\/file$/);
});

test("asset detail exposes a retry when loading fails", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "asset_unavailable" }), {
        status: 503,
        headers: { "Content-Type": "application/json" },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(asset), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  vi.stubGlobal("fetch", fetchMock);
  render(<AssetDetailPage assetId={asset.id} onBack={vi.fn()} />);

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "asset_unavailable",
  );
  fireEvent.click(screen.getByRole("button", { name: "重新加载" }));

  await waitFor(() =>
    expect(screen.getByText("BFS 课堂笔记")).toBeInTheDocument(),
  );
});

test("note asset does not show a missing original-file link", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ...asset,
          kind: "note",
          originalName: null,
          fileAvailable: false,
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    ),
  );

  render(<AssetDetailPage assetId={asset.id} onBack={vi.fn()} />);

  expect(await screen.findByText("BFS 课堂笔记")).toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "打开原始文件" }),
  ).not.toBeInTheDocument();
});
