import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import LearningConnectorDialog from "../src/components/LearningConnectorDialog";
import type { Course } from "../src/types";

const existingCourse: Course = {
  id: "existing-course",
  title: "高等数学",
  description: "已有高数资料",
  color: "#e25d3f",
  assetCount: 2,
  knowledgeCount: 9,
  updatedAt: "2026-11-22T10:00:00Z",
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("connector moves from QR to preview and starts an import", async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/learning/chaoxing/status")) {
      return json({ enabled: true, connection: null });
    }
    if (
      url.endsWith("/learning/chaoxing/login") &&
      init?.method === "POST"
    ) {
      return json(
        {
          id: "login-1",
          status: "pending",
          expiresAt: new Date(Date.now() + 300_000).toISOString(),
          revision: 0,
        },
        201,
      );
    }
    if (url.endsWith("/learning/chaoxing/login/login-1")) {
      return json({
        status: "connected",
        remoteNickname: "林同学",
        message: null,
      });
    }
    if (
      url.endsWith("/learning/chaoxing/previews") &&
      init?.method === "POST"
    ) {
      return json(
        {
          id: "preview-1",
          courses: [
            {
              id: "remote-course-1",
              title: "高等数学",
              teacher: "张老师",
              documents: [
                {
                  id: "file-1",
                  name: "第一章.pdf",
                  extension: ".pdf",
                  sizeBytes: 2048,
                  supported: true,
                  excludedReason: null,
                },
              ],
              videoLinks: ["https://mooc1.chaoxing.com/video/1.mp4"],
            },
          ],
          totalDocuments: 1,
          totalVideoLinks: 1,
          totalBytes: 2048,
          generatedAt: "2026-11-22T10:00:00Z",
          expiresAt: "2026-11-22T10:30:00Z",
        },
        201,
      );
    }
    if (url.endsWith("/learning/imports") && init?.method === "POST") {
      return json(
        {
          id: "job-1",
          previewId: "preview-1",
          status: "queued",
          progress: 0,
          totalItems: 2,
          completedItems: 0,
          failedItems: 0,
          skippedItems: 0,
          cancelRequested: false,
          createdAt: "2026-11-22T10:00:00Z",
          startedAt: null,
          finishedAt: null,
          errorCode: null,
          errorMessage: null,
        },
        201,
      );
    }
    if (url.endsWith("/learning/imports/job-1")) {
      return json({
        job: {
          id: "job-1",
          previewId: "preview-1",
          status: "completed",
          progress: 100,
          totalItems: 2,
          completedItems: 2,
          failedItems: 0,
          skippedItems: 0,
          cancelRequested: false,
          createdAt: "2026-11-22T10:00:00Z",
          startedAt: "2026-11-22T10:00:01Z",
          finishedAt: "2026-11-22T10:00:05Z",
          errorCode: null,
          errorMessage: null,
        },
        items: [
          {
            id: "item-1",
            jobId: "job-1",
            kind: "file",
            title: "第一章.pdf",
            externalCourseId: "remote-course-1",
            externalFileId: "file-1",
            targetCourseId: "existing-course",
            status: "completed",
            attempts: 1,
            checksum: "abc",
            assetId: "asset-1",
            errorCode: null,
            errorMessage: null,
            sizeBytes: 2048,
            createdAt: "2026-11-22T10:00:00Z",
            updatedAt: "2026-11-22T10:00:05Z",
          },
        ],
      });
    }
    return json({ detail: "not_found" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  const onImported = vi.fn();
  render(
    <LearningConnectorDialog
      open
      courses={[existingCourse]}
      onClose={vi.fn()}
      onImported={onImported}
    />,
  );

  fireEvent.click(
    await screen.findByRole("button", { name: "生成学习通二维码" }),
  );

  expect(await screen.findByText("选择要导入的课程", {}, { timeout: 4000 }))
    .toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("checkbox", { name: /高等数学/ }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "下一步：设置文件夹" }),
  );

  expect(
    screen.getByRole("combobox", { name: "高等数学 导入方式" }),
  ).toHaveValue("merge");
  expect(
    screen.getByRole("combobox", { name: "高等数学 目标文件夹" }),
  ).toHaveValue(existingCourse.id);

  fireEvent.click(screen.getByRole("button", { name: "确认导入" }));

  await waitFor(() => expect(onImported).toHaveBeenCalled());
  expect(await screen.findByText("导入完成")).toBeInTheDocument();
  expect(
    screen.getByRole("progressbar"),
  ).toHaveAttribute("aria-valuenow", "100");
});

test("connector surfaces an actionable error if login cannot start", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/learning/chaoxing/status")) {
        return json({ enabled: true, connection: null });
      }
      if (
        url.endsWith("/learning/chaoxing/login") &&
        init?.method === "POST"
      ) {
        return json({ detail: "connector_disabled" }, 503);
      }
      return json({ detail: "not_found" }, 404);
    }),
  );
  render(
    <LearningConnectorDialog
      open
      courses={[]}
      onClose={vi.fn()}
      onImported={vi.fn()}
    />,
  );

  fireEvent.click(
    await screen.findByRole("button", { name: "生成学习通二维码" }),
  );

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "学习通连接功能尚未启用",
  );
});

test("disabled connector explains why the action is unavailable", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      json({ enabled: false, connection: null }),
    ),
  );
  render(
    <LearningConnectorDialog
      open
      courses={[]}
      onClose={vi.fn()}
      onImported={vi.fn()}
    />,
  );

  expect(await screen.findByText("学习通在线连接未开启")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "生成学习通二维码" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "选择 ZIP 资料包" }),
  ).toBeInTheDocument();
});

test("ZIP fallback opens a preview even when the connector is disabled", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/learning/chaoxing/status")) {
        return json({ enabled: false, connection: null });
      }
      if (url.endsWith("/learning/imports/zip/previews")) {
        return json(
          {
            id: "zip-preview",
            courses: [
              {
                id: "zip-course",
                title: "离散数学",
                teacher: "",
                documents: [
                  {
                    id: "zip-file",
                    name: "集合.md",
                    extension: ".md",
                    sizeBytes: 20,
                    supported: true,
                    excludedReason: null,
                  },
                ],
                videoLinks: [],
              },
            ],
            totalDocuments: 1,
            totalVideoLinks: 0,
            totalBytes: 20,
            generatedAt: "2026-11-22T10:00:00Z",
            expiresAt: "2026-11-22T10:30:00Z",
          },
          201,
        );
      }
      return json({ detail: "not_found" }, 404);
    }),
  );
  render(
    <LearningConnectorDialog
      open
      courses={[]}
      onClose={vi.fn()}
      onImported={vi.fn()}
    />,
  );
  await screen.findByText("学习通在线连接未开启");
  const input = screen.getByLabelText("选择 ZIP 资料包");
  fireEvent.change(input, {
    target: {
      files: [new File(["PK"], "资料.zip", { type: "application/zip" })],
    },
  });

  expect(await screen.findByText("选择要导入的课程")).toBeInTheDocument();
  expect(screen.getByText("离散数学")).toBeInTheDocument();
});
