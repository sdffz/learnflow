import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import LearningConnectorDialog from "../src/components/LearningConnectorDialog";

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

function renderDialog() {
  return render(
    <LearningConnectorDialog
      open
      courses={[]}
      onClose={vi.fn()}
      onImported={vi.fn()}
    />,
  );
}

test("a failed status probe offers a retry instead of a dead QR button", async () => {
  // Regression: any status() error was treated as "not connected", so the
  // dialog rendered 生成二维码 which could only fail with connector_disabled.
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(json({ detail: "boom" }, 500)),
  );

  renderDialog();

  expect(await screen.findByText("暂时读不到连接器状态")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "重新检查" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "生成学习通二维码" }),
  ).not.toBeInTheDocument();
});

test("retry after a failed probe recovers into the normal state", async () => {
  let calls = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      calls += 1;
      if (calls === 1) return json({ detail: "boom" }, 500);
      return json({ enabled: false, connection: null });
    }),
  );

  renderDialog();
  await screen.findByText("暂时读不到连接器状态");

  fireEvent.click(screen.getByRole("button", { name: "重新检查" }));

  expect(
    await screen.findByText("学习通在线连接未开启"),
  ).toBeInTheDocument();
});

test("an expired login returns to a state where a new code can be generated", async () => {
  // Regression: login_not_found left the user on a screen whose only action
  // could never succeed, with a raw error message.
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/learning/chaoxing/status")) {
        return json({ enabled: true, connection: null });
      }
      if (url.endsWith("/learning/chaoxing/login")) {
        return json(
          {
            id: "login-1",
            status: "pending",
            expiresAt: new Date(Date.now() + 300_000).toISOString(),
            revision: 1,
            message: null,
          },
          201,
        );
      }
      if (url.includes("/learning/chaoxing/login/login-1")) {
        return json({ detail: "login_not_found" }, 404);
      }
      return json({ detail: "not_found" }, 404);
    }),
  );

  renderDialog();
  fireEvent.click(
    await screen.findByRole("button", { name: "生成学习通二维码" }),
  );

  expect(
    await screen.findByText("二维码已失效，请重新生成。"),
  ).toBeInTheDocument();
  // The generate button is usable again rather than the dialog being stuck.
  expect(
    await screen.findByRole("button", { name: "生成学习通二维码" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByText("扫码会话不存在，请重新生成二维码。"),
  ).not.toBeInTheDocument();
});
