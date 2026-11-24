import { afterEach, expect, test, vi } from "vitest";

import { knowledgeApi } from "../src/api";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("asset upload sends multipart data without a JSON content type", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        id: "asset-1",
        courseId: "course-1",
        courseTitle: "数据结构",
        kind: "file",
        title: "BFS 笔记",
        originalName: "bfs.md",
        mimeType: "text/markdown",
        status: "ready",
        summary: "广度优先搜索使用队列",
        content: "广度优先搜索使用队列",
        tags: ["图论"],
        knowledgeCount: 1,
        error: null,
        createdAt: "2026-11-21T00:00:00Z",
        updatedAt: "2026-11-21T00:00:00Z",
        chunks: [],
      }),
      {
        status: 201,
        headers: { "Content-Type": "application/json" },
      },
    ),
  );
  vi.stubGlobal("fetch", fetchMock);

  const file = new File(["# BFS\n\n广度优先搜索使用队列"], "bfs.md", {
    type: "text/markdown",
  });
  await knowledgeApi.uploadAsset("course-1", file, {
    title: "BFS 笔记",
    tags: ["图论", "搜索"],
  });

  const init = fetchMock.mock.calls[0][1] as RequestInit;
  const body = init.body as FormData;
  expect(body).toBeInstanceOf(FormData);
  expect(body.get("title")).toBe("BFS 笔记");
  expect(body.get("tags")).toBe("图论,搜索");
  expect(new Headers(init.headers).has("Content-Type")).toBe(false);
});

test("knowledge search keeps query and tag when building the request URL", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ items: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);

  await knowledgeApi.search("广度优先", "图论");

  const requestedUrl = new URL(String(fetchMock.mock.calls[0][0]));
  expect(`${requestedUrl.pathname}${requestedUrl.search}`).toBe(
    "/api/knowledge/search?q=%E5%B9%BF%E5%BA%A6%E4%BC%98%E5%85%88&tag=%E5%9B%BE%E8%AE%BA",
  );
});

test("delete accepts an empty 204 response", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(null, { status: 204 })),
  );

  await expect(knowledgeApi.deleteCourse("course-1")).resolves.toBeUndefined();
});
