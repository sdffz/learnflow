import { afterEach, expect, test } from "vitest";

import type { Learner } from "../src/types";
import {
  clearWorkspace,
  createDefaultWorkspace,
  deriveNextAction,
  loadWorkspace,
  saveWorkspace,
} from "../src/workspace";

const dimension = {
  value: "测试",
  evidence: "测试",
  confidence: 0.8,
  updated_at: "2026-11-21T00:00:00Z",
};

const learner: Learner = {
  id: "l1",
  name: "学生",
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

afterEach(() => {
  window.localStorage.clear();
});

test("idle learner is directed to resource generation", () => {
  expect(deriveNextAction(learner, createDefaultWorkspace()).target).toBe(
    "studio",
  );
});

test("running generation is resumed from the studio", () => {
  const action = deriveNextAction(learner, {
    ...createDefaultWorkspace(),
    latestRunId: "run-1",
    latestRunStatus: "running",
  });

  expect(action.label).toBe("恢复生成进度");
  expect(action.target).toBe("studio");
});

test("completed resources without a path are directed to path planning", () => {
  const state = {
    ...createDefaultWorkspace(),
    latestRunId: "r1",
    latestRunStatus: "completed" as const,
    resourceCount: 6,
  };

  expect(deriveNextAction(learner, state).target).toBe("path");
});

test("assessment is offered after a generated path", () => {
  const state = {
    ...createDefaultWorkspace(),
    latestRunId: "r1",
    latestRunStatus: "completed" as const,
    resourceCount: 6,
    pathGenerated: true,
  };

  expect(deriveNextAction(learner, state).target).toBe("assessment");
});

test("existing assessment is directed to tutoring", () => {
  const state = {
    ...createDefaultWorkspace(),
    latestRunId: "r1",
    latestRunStatus: "completed" as const,
    resourceCount: 6,
    pathGenerated: true,
    lastAssessmentScore: 88,
  };

  expect(deriveNextAction(learner, state).target).toBe("tutor");
});

test("invalid stored workspace falls back to defaults", () => {
  window.localStorage.setItem("learnflow_workspace", "{broken");

  expect(loadWorkspace()).toEqual(createDefaultWorkspace());
});

test("saved workspace can be restored", () => {
  const state = { ...createDefaultWorkspace(), activeTopic: "机器学习" };

  saveWorkspace(state);

  expect(loadWorkspace()).toEqual(state);
});

test("workspace with another course is discarded", () => {
  window.localStorage.setItem(
    "learnflow_workspace",
    JSON.stringify({ ...createDefaultWorkspace(), courseId: "other-course" }),
  );

  expect(loadWorkspace()).toEqual(createDefaultWorkspace());
});

test("clearWorkspace removes persisted state", () => {
  saveWorkspace(createDefaultWorkspace());

  clearWorkspace();

  expect(window.localStorage.getItem("learnflow_workspace")).toBeNull();
});
