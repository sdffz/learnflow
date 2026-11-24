import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import AgentTimeline from "../src/components/AgentTimeline";
import ResourcePanel from "../src/components/ResourcePanel";
import type { AgentEvent, LearningResource } from "../src/types";

const resources: LearningResource[] = [
  {
    id: "1",
    type: "document",
    title: "神经网络讲解",
    knowledge_point: "神经网络",
    content: { markdown: "# 内容" },
    metadata: {},
    status: "verified",
  },
  {
    id: "2",
    type: "quiz",
    title: "神经网络练习",
    knowledge_point: "神经网络",
    content: { questions: [] },
    metadata: {},
    status: "verified",
  },
];

const events: AgentEvent[] = [
  {
    sequence: 1,
    run_id: "r",
    agent: "document",
    phase: "resource",
    status: "completed",
    summary: "讲解文档完成",
    data: {},
    created_at: "2026-01-01T00:00:00Z",
  },
  {
    sequence: 2,
    run_id: "r",
    agent: "animation",
    phase: "resource",
    status: "failed",
    summary: "动画生成失败",
    data: {},
    created_at: "2026-01-01T00:00:01Z",
  },
];

test("resource panel switches between resource types", () => {
  render(<ResourcePanel resources={resources} />);

  fireEvent.click(screen.getByRole("tab", { name: "练习题目" }));

  expect(screen.getByText("神经网络练习")).toBeInTheDocument();
});

test("resource panel selects the first available type after async loading", () => {
  const { rerender } = render(<ResourcePanel resources={[]} />);
  const mindmap: LearningResource = {
    id: "3",
    type: "mindmap",
    title: "神经网络知识导图",
    knowledge_point: "神经网络",
    content: {
      root: {
        label: "神经网络",
        children: [{ id: "a", label: "神经元" }],
      },
    },
    metadata: {},
    status: "verified",
  };

  rerender(<ResourcePanel resources={[mindmap]} />);

  expect(screen.getByRole("tab", { name: "知识导图" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(screen.getByText("神经网络知识导图")).toBeInTheDocument();
});

test("resource panel exposes personal knowledge citations", () => {
  render(
    <ResourcePanel
      resources={[
        {
          ...resources[0],
          metadata: {
            sources: [
              {
                assetId: "asset-1",
                assetTitle: "BFS 课堂笔记",
                courseTitle: "算法",
                title: "广度优先搜索",
                excerpt: "广度优先搜索使用队列。",
              },
            ],
          },
        },
      ]}
    />,
  );

  expect(screen.getByText("知识来源")).toBeInTheDocument();
  expect(screen.getByText("算法 · BFS 课堂笔记")).toBeInTheDocument();
});

test("timeline exposes completed and failed agent states", () => {
  render(<AgentTimeline events={events} />);

  expect(screen.getByText("讲解文档完成")).toBeInTheDocument();
  expect(screen.getByText("动画生成失败")).toBeInTheDocument();
  expect(screen.getByText("失败")).toBeInTheDocument();
});
