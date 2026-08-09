import { useState } from "react";

import type { StatsProjectCost } from "../../api/runApi";

// Cost split by project. Capped at THREE colored slices plus "Other":
// slots 1-3 are the subset validated all-pairs against this dark surface
// (worst CVD dE 9.4, worst normal-vision dE 20.9); the 4th slot puts
// yellow beside orange, which fails the all-pairs floors. Overflow folds
// into a neutral "Other" rather than generating a 4th hue — the dataviz
// skill's explicit rule for running out of validated slots.

const SLOT_COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)"];
const OTHER_COLOR = "var(--text-muted)";
const MAX_COLORED_SLICES = 3;

const SIZE = 148;
const RADIUS = 62;
const THICKNESS = 22;

interface Slice {
  label: string;
  value: number;
  color: string;
}

function polar(cx: number, cy: number, r: number, angleDeg: number) {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

function arcPath(startAngle: number, endAngle: number): string {
  const c = SIZE / 2;
  const outer = RADIUS;
  const inner = RADIUS - THICKNESS;
  const largeArc = endAngle - startAngle > 180 ? 1 : 0;
  const o1 = polar(c, c, outer, startAngle);
  const o2 = polar(c, c, outer, endAngle);
  const i2 = polar(c, c, inner, endAngle);
  const i1 = polar(c, c, inner, startAngle);
  return [
    `M${o1.x},${o1.y}`,
    `A${outer},${outer} 0 ${largeArc} 1 ${o2.x},${o2.y}`,
    `L${i2.x},${i2.y}`,
    `A${inner},${inner} 0 ${largeArc} 0 ${i1.x},${i1.y}`,
    "Z",
  ].join(" ");
}

function toSlices(costs: StatsProjectCost[], labelFor: (projectId: string) => string): Slice[] {
  const spending = costs.filter((c) => c.cost_usd > 0);
  const head = spending.slice(0, MAX_COLORED_SLICES).map((c, i) => ({
    label: labelFor(c.project_id),
    value: c.cost_usd,
    // slice() above already bounds i to the validated slots; the fallback
    // only satisfies the compiler's index check.
    color: SLOT_COLORS[i] ?? OTHER_COLOR,
  }));
  const tail = spending.slice(MAX_COLORED_SLICES);
  if (tail.length > 0) {
    head.push({
      label: `Other (${tail.length})`,
      value: tail.reduce((sum, c) => sum + c.cost_usd, 0),
      color: OTHER_COLOR,
    });
  }
  return head;
}

interface Props {
  costs: StatsProjectCost[];
  total: number;
  /** Resolves a project_id to the name the SDK was configured with.
   * Defaults to identity so callers that don't have the lookup handy
   * (tests, storybook) still get a label instead of a crash. */
  labelFor?: (projectId: string) => string;
}

export default function CostDonut({ costs, total, labelFor = (id) => id }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const slices = toSlices(costs, labelFor);

  if (slices.length === 0) {
    return (
      <div className="chart-empty">
        No cost recorded yet — these demo runs use a deterministic fixture LLM that reports $0.
      </div>
    );
  }

  const sum = slices.reduce((s, x) => s + x.value, 0) || 1;
  let cursor = 0;
  const arcs = slices.map((slice) => {
    const sweep = (slice.value / sum) * 360;
    const arc = { slice, start: cursor, end: cursor + sweep };
    cursor += sweep;
    return arc;
  });

  return (
    <div className="row" style={{ gap: 18, alignItems: "center" }}>
      <svg
        width={SIZE}
        height={SIZE}
        role="img"
        aria-label="Cost by project"
        style={{ flex: "none" }}
      >
        {arcs.map((arc, i) => (
          <path
            key={arc.slice.label}
            // A full-circle single slice can't be drawn as an arc (start
            // and end coincide) — draw it as a ring stroke instead.
            d={
              arcs.length === 1
                ? `M${SIZE / 2},${SIZE / 2 - RADIUS + THICKNESS / 2}
                   a${RADIUS - THICKNESS / 2},${RADIUS - THICKNESS / 2} 0 1 1 -0.01 0`
                : arcPath(arc.start, arc.end)
            }
            fill={arcs.length === 1 ? "none" : arc.slice.color}
            stroke={arcs.length === 1 ? arc.slice.color : "var(--surface-1)"}
            /* 2px surface gap between adjacent fills */
            strokeWidth={arcs.length === 1 ? THICKNESS : 2}
            opacity={hover === null || hover === i ? 1 : 0.45}
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
          />
        ))}
        <text
          x={SIZE / 2}
          y={SIZE / 2 - 4}
          textAnchor="middle"
          fontSize="17"
          fontWeight="640"
          fill="var(--text-primary)"
        >
          ${total.toFixed(2)}
        </text>
        <text
          x={SIZE / 2}
          y={SIZE / 2 + 13}
          textAnchor="middle"
          fontSize="10.5"
          fill="var(--text-muted)"
        >
          total
        </text>
      </svg>

      {/* Legend doubles as the table view: every slice's exact value is
          readable without hovering, so identity never rides on hue. */}
      <div className="donut-legend">
        {slices.map((slice, i) => (
          <div
            key={slice.label}
            className="donut-legend__row"
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
          >
            <span className="donut-legend__swatch" style={{ background: slice.color }} />
            <span className="donut-legend__name" title={slice.label}>
              {slice.label}
            </span>
            <span className="donut-legend__value">
              ${slice.value.toFixed(2)} · {((slice.value / sum) * 100).toFixed(0)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
