import { render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import StudioPage, { topicFromProfile } from "../src/pages/StudioPage";
import type { Course, Learner } from "../src/types";
import { createDefaultWorkspace } from "../src/workspace";

function learnerWith(dimensions: Record<string, string>): Learner {
  return {
    id: "l1",
    name: "测试学生",
    course_id: "ai-intro",
    persona_id: null,
    profile: {
      dimensions: Object.fromEntries(
        Object.entries(dimensions).map(([name, value]) => [
          name,
          { value, evidence: value, confidence: 0.9, updated_at: "2026-11-24T00:00:00Z" },
        ]),
      ),
      mastery: {},
    },
  };
}

const course: Course = {
  id: "c1",
  title: "人工智能导论",
  description: "示例课程",
  color: "#e25d3f",
  knowledgeCount: 5,
} as Course;

describe("topic derivation", () => {
  test("weak point wins over interest and goal", () => {
    const learner = learnerWith({
      当前薄弱点: "数据结构比较薄弱",
      兴趣方向: "机器人",
      学习目标: "完成项目",
    });

    expect(topicFromProfile(learner)).toBe("数据结构");
  });

  test("interest is used when there is no weak point", () => {
    const learner = learnerWith({ 兴趣方向: "多模态生成" });

    expect(topicFromProfile(learner)).toBe("多模态生成");
  });

  test("qualifiers are stripped from the captured phrasing", () => {
    expect(topicFromProfile(learnerWith({ 当前薄弱点: "操作系统没掌握" }))).toBe(
      "操作系统",
    );
    expect(topicFromProfile(learnerWith({ 当前薄弱点: "对密码学不熟悉" }))).toBe(
      "密码学",
    );
  });

  test("empty profile yields no topic rather than a default", () => {
    expect(topicFromProfile(learnerWith({}))).toBe("");
    expect(topicFromProfile(null)).toBe("");
  });
});

test("studio starts from the profile instead of a hardcoded topic", () => {
  const onWorkspaceChange = vi.fn();
  const learner = learnerWith({ 当前薄弱点: "数据结构比较薄弱", 兴趣方向: "机器人" });

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

  // The topic input follows the profile, so a learner who said 数据结构薄弱 no
  // longer receives 神经网络 material.
  const input = screen.getByLabelText("学习主题") as HTMLInputElement;
  expect(input.value).toBe("数据结构");
  expect(onWorkspaceChange).toHaveBeenCalledWith({ activeTopic: "数据结构" });
});

test("an explicitly chosen topic is never overwritten", () => {
  const onWorkspaceChange = vi.fn();
  const learner = learnerWith({ 当前薄弱点: "数据结构比较薄弱" });

  render(
    <StudioPage
      learner={learner}
      onNeedLearner={() => undefined}
      workspace={{ ...createDefaultWorkspace(), activeTopic: "机器学习" }}
      onWorkspaceChange={onWorkspaceChange}
      onNavigate={() => undefined}
      courses={[course]}
    />,
  );

  const input = screen.getByLabelText("学习主题") as HTMLInputElement;
  expect(input.value).toBe("机器学习");
  expect(onWorkspaceChange).not.toHaveBeenCalled();
});
