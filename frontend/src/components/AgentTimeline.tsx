import { Check, CircleDashed, LoaderCircle, TriangleAlert } from "lucide-react";

import type { AgentEvent } from "../types";

interface Props {
  events: AgentEvent[];
}

const labels: Record<string, string> = {
  completed: "完成",
  failed: "失败",
  running: "进行中",
  partial: "部分完成",
};

export default function AgentTimeline({ events }: Props) {
  if (!events.length) {
    return (
      <div className="timeline-empty">
        <CircleDashed size={20} />
        等待智能体启动
      </div>
    );
  }

  return (
    <ol className="agent-timeline" aria-label="智能体运行时间线">
      {events.map((event) => {
        const Icon =
          event.status === "failed"
            ? TriangleAlert
            : event.status === "completed"
              ? Check
              : event.status === "partial"
                ? TriangleAlert
                : LoaderCircle;
        return (
          <li key={`${event.run_id}-${event.sequence}`} data-status={event.status}>
            <span className="timeline-icon">
              <Icon size={15} className={event.status === "running" ? "spin" : ""} />
            </span>
            <div>
              <span className="timeline-agent">{event.agent}</span>
              <p>{event.summary}</p>
            </div>
            <span className="timeline-status">{labels[event.status] ?? event.status}</span>
          </li>
        );
      })}
    </ol>
  );
}
