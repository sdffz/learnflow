import { useState } from "react";
import { ChevronRight } from "lucide-react";

interface MindMapNode {
  id?: string;
  label: string;
  children?: MindMapNode[];
}

interface Props {
  root: MindMapNode;
}

/**
 * Two-pane mind map: branches stack down the left, the selected branch opens
 * its children on the right.
 *
 * The previous version was a nested <ul> that grew to ~2700px tall, which read
 * as an outline rather than a map and buried the structure under scrolling.
 */
export default function MindMap({ root }: Props) {
  const branches = root.children ?? [];
  const [activeIndex, setActiveIndex] = useState(0);
  const active = branches[Math.min(activeIndex, branches.length - 1)];
  const children = (active?.children ?? []) as MindMapNode[];

  if (!branches.length) {
    return <div className="mindmap-empty">这张知识地图还没有分支。</div>;
  }

  return (
    <div className="mindmap-grid">
      <div className="mindmap-root">
        <span className="mindmap-root-label">{root.label}</span>
        <small>{branches.length} 个主干</small>
      </div>

      <div className="mindmap-columns">
        <ol className="mindmap-branches" aria-label="知识主干">
          {branches.map((branch, index) => (
            <li key={branch.id ?? branch.label}>
              <button
                className={index === activeIndex ? "active" : ""}
                aria-current={index === activeIndex ? "true" : undefined}
                onClick={() => setActiveIndex(index)}
              >
                <span className="mindmap-index">{String(index + 1).padStart(2, "0")}</span>
                <span className="mindmap-branch-label">{branch.label}</span>
                {branch.children?.length ? (
                  <span className="mindmap-count">{branch.children.length}</span>
                ) : null}
                <ChevronRight size={15} />
              </button>
            </li>
          ))}
        </ol>

        <div className="mindmap-detail" aria-live="polite">
          <span className="resource-kicker">SELECTED BRANCH</span>
          <h4>{active?.label}</h4>
          {children.length ? (
            <ul>
              {children.map((child) => (
                <li key={child.id ?? child.label}>{child.label}</li>
              ))}
            </ul>
          ) : (
            <p className="mindmap-detail-empty">这一支是叶子节点，没有更细的拆分。</p>
          )}
        </div>
      </div>
    </div>
  );
}
