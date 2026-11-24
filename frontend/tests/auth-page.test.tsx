import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import AuthPage from "../src/pages/AuthPage";

const auth = {
  user: { id: "user-1", name: "林同学", email: "student@example.com" },
  workspace: { id: "workspace-1", name: "林同学的知识空间", role: "owner" },
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("login form authenticates an existing user", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(auth), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  const onAuthenticated = vi.fn();
  render(<AuthPage onAuthenticated={onAuthenticated} />);

  fireEvent.change(screen.getByLabelText("邮箱"), {
    target: { value: "student@example.com" },
  });
  fireEvent.change(screen.getByLabelText("密码"), {
    target: { value: "StrongPass123" },
  });
  fireEvent.click(screen.getByRole("button", { name: "登录" }));

  await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith(auth));
});

test("registration requires matching passwords and creates an account", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(auth), {
      status: 201,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  const onAuthenticated = vi.fn();
  render(<AuthPage onAuthenticated={onAuthenticated} />);

  fireEvent.click(screen.getByRole("button", { name: "创建账号" }));
  fireEvent.change(screen.getByLabelText("姓名"), {
    target: { value: "林同学" },
  });
  fireEvent.change(screen.getByLabelText("邮箱"), {
    target: { value: "student@example.com" },
  });
  fireEvent.change(screen.getByLabelText("密码"), {
    target: { value: "StrongPass123" },
  });
  fireEvent.change(screen.getByLabelText("确认密码"), {
    target: { value: "DifferentPass123" },
  });
  fireEvent.click(screen.getByRole("button", { name: "注册并进入" }));

  expect(screen.getByRole("alert")).toHaveTextContent("两次输入的密码不一致");
  expect(fetchMock).not.toHaveBeenCalled();
});

test("login failure remains on the form with a safe error message", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "invalid_credentials" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  render(<AuthPage onAuthenticated={vi.fn()} />);

  fireEvent.change(screen.getByLabelText("邮箱"), {
    target: { value: "student@example.com" },
  });
  fireEvent.change(screen.getByLabelText("密码"), {
    target: { value: "WrongPass123" },
  });
  fireEvent.click(screen.getByRole("button", { name: "登录" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "邮箱或密码不正确",
  );
});
