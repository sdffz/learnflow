import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import CaptureDialog from "../src/components/CaptureDialog";
import CourseDetailPage from "../src/pages/CourseDetailPage";
import CoursesPage from "../src/pages/CoursesPage";
import type { Course, KnowledgeChunk } from "../src/types";

const course: Course = {
  id: "course-1",
  title: "数据结构",
  description: "链表、树与图",
  color: "#e25d3f",
  assetCount: 3,
  knowledgeCount: 12,
  updatedAt: "2026-11-21T10:00:00Z",
};

const asset = {
  id: "asset-1",
  courseId: course.id,
  courseTitle: course.title,
  kind: "note" as const,
  title: "BFS 课堂笔记",
  originalName: null,
  mimeType: null,
  status: "ready" as const,
  summary: "广度优先搜索使用队列。",
  content: "广度优先搜索使用队列。",
  tags: ["图论"],
  knowledgeCount: 1,
  error: null,
  createdAt: "2026-11-21T10:00:00Z",
  updatedAt: "2026-11-21T10:00:00Z",
  chunks: [],
};

const chunk: KnowledgeChunk = {
  id: "chunk-1",
  assetId: asset.id,
  assetTitle: asset.title,
  courseId: course.id,
  courseTitle: course.title,
  title: "广度优先搜索",
  excerpt: "广度优先搜索使用队列逐层访问节点。",
  tags: ["图论", "搜索"],
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("capture dialog exposes file, camera and note modes", () => {
  render(
    <CaptureDialog
      courses={[course]}
      onClose={vi.fn()}
      onCreated={vi.fn()}
    />,
  );

  expect(screen.getByRole("tab", { name: "上传文件" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "拍照/图片" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "快速笔记" })).toBeInTheDocument();
});

test("quick note reports a successful knowledge extraction", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(asset), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  const onCreated = vi.fn();
  render(
    <CaptureDialog
      courses={[course]}
      initialCourseId={course.id}
      onClose={vi.fn()}
      onCreated={onCreated}
    />,
  );

  fireEvent.click(screen.getByRole("tab", { name: "快速笔记" }));
  fireEvent.change(screen.getByLabelText("资料标题"), {
    target: { value: "BFS 课堂笔记" },
  });
  fireEvent.change(screen.getByLabelText("资料内容"), {
    target: { value: "广度优先搜索使用队列。" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存笔记" }));

  expect(await screen.findByRole("status")).toHaveTextContent(
    "已入库，提取 1 个知识片段",
  );
  expect(onCreated).toHaveBeenCalledWith(asset);
});

test("course deletion requires confirmation", () => {
  const onDelete = vi.fn().mockResolvedValue(undefined);
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(
    <CoursesPage
      courses={[course]}
      loading={false}
      error={null}
      onCreate={vi.fn()}
      onOpen={vi.fn()}
      onRefresh={vi.fn()}
      onDelete={onDelete}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "删除 数据结构" }));

  expect(confirm).toHaveBeenCalledWith(
    "删除《数据结构》将同时删除其中的资料和知识片段，确定继续吗？",
  );
  expect(onDelete).not.toHaveBeenCalled();
});

test("course creation keeps the form and reports an error when saving fails", async () => {
  const onCreate = vi.fn().mockRejectedValue(new Error("course_unavailable"));
  render(
    <CoursesPage
      courses={[]}
      loading={false}
      error={null}
      onCreate={onCreate}
      onOpen={vi.fn()}
      onRefresh={vi.fn()}
      onDelete={vi.fn()}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "创建文件夹" }));
  fireEvent.change(screen.getByLabelText("文件夹名称"), {
    target: { value: "操作系统" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存文件夹" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "course_unavailable",
  );
  expect(screen.getByLabelText("文件夹名称")).toHaveValue("操作系统");
});

test("knowledge folder shows extracted knowledge points", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes(`/courses/${course.id}/assets`)) {
        return new Response(JSON.stringify({ items: [asset] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.includes("/knowledge/search") && url.includes(`courseId=${course.id}`)) {
        return new Response(JSON.stringify({ items: [chunk] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify({ detail: "not_found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  render(
    <CourseDetailPage
      course={course}
      onBack={vi.fn()}
      onCapture={vi.fn()}
      onOpenAsset={vi.fn()}
    />,
  );

  expect(await screen.findByText("文件夹知识点")).toBeInTheDocument();
  expect(screen.getByText("广度优先搜索")).toBeInTheDocument();
});

test("knowledge folder can be renamed by the user", async () => {
  const onUpdate = vi.fn().mockResolvedValue(undefined);
  render(
    <CoursesPage
      courses={[course]}
      loading={false}
      error={null}
      onCreate={vi.fn()}
      onUpdate={onUpdate}
      onOpen={vi.fn()}
      onRefresh={vi.fn()}
      onDelete={vi.fn()}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "重命名 数据结构" }));
  fireEvent.change(screen.getByLabelText("文件夹名称"), {
    target: { value: "算法与数据结构" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存重命名" }));

  await waitFor(() =>
    expect(onUpdate).toHaveBeenCalledWith(course.id, {
      title: "算法与数据结构",
      description: course.description,
    }),
  );
});

test("note success callback runs only after the request resolves", async () => {
  let resolveFetch: (response: Response) => void = () => undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        }),
    ),
  );
  const onCreated = vi.fn();
  render(
    <CaptureDialog
      courses={[course]}
      initialCourseId={course.id}
      onClose={vi.fn()}
      onCreated={onCreated}
    />,
  );

  fireEvent.click(screen.getByRole("tab", { name: "快速笔记" }));
  fireEvent.change(screen.getByLabelText("资料标题"), {
    target: { value: "BFS 课堂笔记" },
  });
  fireEvent.change(screen.getByLabelText("资料内容"), {
    target: { value: "广度优先搜索使用队列。" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存笔记" }));

  expect(screen.getByRole("button", { name: "正在保存" })).toBeDisabled();
  expect(onCreated).not.toHaveBeenCalled();

  resolveFetch(
    new Response(JSON.stringify(asset), {
      status: 201,
      headers: { "Content-Type": "application/json" },
    }),
  );

  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(asset));
});
