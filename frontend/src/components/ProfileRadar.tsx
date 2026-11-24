import type { LearnerProfile } from "../types";

interface Props {
  profile: LearnerProfile;
}

const center = 120;
const radius = 82;

/** Fixed axis order so the polygon keeps its shape as dimensions arrive. */
const DIMENSION_ORDER = [
  "先修知识",
  "学习目标",
  "认知风格",
  "当前薄弱点",
  "资源偏好",
  "学习节奏",
  "编程基础",
  "兴趣方向",
];

function point(index: number, total: number, ratio: number) {
  const angle = -Math.PI / 2 + (Math.PI * 2 * index) / total;
  return [center + Math.cos(angle) * radius * ratio, center + Math.sin(angle) * radius * ratio];
}

export default function ProfileRadar({ profile }: Props) {
  const entries = [...DIMENSION_ORDER, ...Object.keys(profile.dimensions)].filter(
    (name, index, all) => all.indexOf(name) === index,
  );
  const known = entries.filter((name) => profile.dimensions[name]);
  if (!known.length) {
    return <div className="radar-empty">完成画像访谈后生成学习坐标</div>;
  }

  const total = entries.length;
  // Axis length encodes how confident the system is about that dimension, so a
  // missing dimension sits at the centre instead of reshaping the polygon.
  const ratioOf = (name: string) => {
    const dimension = profile.dimensions[name];
    return dimension ? Math.max(0.12, dimension.confidence) : 0;
  };
  const polygon = entries
    .map((name, index) => point(index, total, ratioOf(name)).join(","))
    .join(" ");

  return (
    <div className="radar-wrap">
      <svg
        className="radar"
        viewBox="0 0 240 240"
        role="img"
        aria-label="学习者画像雷达图"
      >
        {[0.25, 0.5, 0.75, 1].map((ratio) => (
          <polygon
            key={ratio}
            points={entries
              .map((_, index) => point(index, total, ratio).join(","))
              .join(" ")}
            fill="none"
            stroke="rgba(21,50,74,.12)"
          />
        ))}
        {entries.map((name, index) => {
          const [x, y] = point(index, total, 1);
          const has = Boolean(profile.dimensions[name]);
          return (
            <g key={name}>
              <line
                x1={center}
                y1={center}
                x2={x}
                y2={y}
                stroke="rgba(21,50,74,.09)"
              />
              <text
                x={point(index, total, 1.18)[0]}
                y={point(index, total, 1.18)[1]}
                textAnchor={x > center + 2 ? "start" : x < center - 2 ? "end" : "middle"}
                dominantBaseline="middle"
                className="radar-label"
                opacity={has ? 1 : 0.38}
              >
                {name}
              </text>
            </g>
          );
        })}
        <polygon
          points={polygon}
          fill="rgba(226,93,63,.18)"
          stroke="#e25d3f"
          strokeWidth="2"
        />
        {entries.map((name, index) => {
          const dimension = profile.dimensions[name];
          if (!dimension) return null;
          const [x, y] = point(index, total, ratioOf(name));
          return <circle key={name} cx={x} cy={y} r="3.5" fill="#e25d3f" />;
        })}
      </svg>
    </div>
  );
}
