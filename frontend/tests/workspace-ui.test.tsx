import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import WorkspaceBar from "../src/components/WorkspaceBar";
import type { Learner } from "../src/types";
import { createDefaultWorkspace } from "../src/workspace";

const dimension = {
  value: "测试",
  evidence: "测试",
  confidence: 0.8,
  updated_at: "2026-11-21T00:00:00Z",
};

const learner: Learner = {
  id: "l1",
  name: "测试学生",
  course_id: "ai-intro",
  persona_id: "beginner",
  profile: {
    dimensions: {
      a: dimension,
      b: dimension,
      c: dimension,
      d: dimension,
      e: dimension,
      f: dimension,
    },
    mastery: {},
  },
};

test("workspace bar shows current topic and next action", () => {
  const navigate = vi.fn();
  const state = {
    ...createDefaultWorkspace(),
    // The topic now comes from the profile rather than a fixed default, so a
    // checked run states it explicitly.
    activeTopic: "神经网络",
    latestRunId: "run-1",
    latestRunStatus: "completed" as const,
    resourceCount: 6,
  };

  render(
    <WorkspaceBar
      learner={learner}
      workspace={state}
      active="path"
      onNavigate={navigate}
    />,
  );

  expect(screen.getByText(/人工智能导论 · 神经网络/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "学习路径 待规划" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  fireEvent.click(screen.getByRole("button", { name: "规划学习路径" }));
  expect(navigate).toHaveBeenCalledWith("path");
});

test("partial resources are not reported as complete", () => {
  render(
    <WorkspaceBar
      learner={learner}
      workspace={{
        ...createDefaultWorkspace(),
        latestRunId: "run-1",
        latestRunStatus: "partial",
        resourceCount: 4,
      }}
      active="studio"
      onNavigate={vi.fn()}
    />,
  );

  expect(screen.getByText("学习资源 4/6 · 部分完成")).toBeInTheDocument();
});
