import { useState } from "react";

import type { StatsDailyPoint } from "../../api/runApi";

// Two series on ONE y-axis (runs and failed runs are the same unit —
// counts — so they share a scale; the dataviz skill's hardest rule is
// never a second y-scale). Colors: categorical slot 1 for the total,
// the fixed status-critical step for failures, validated together
// against this dark surface (all-pairs CVD dE 25.7, normal-vision 31.9).
// Failure is a state, not a series identity, which is exactly what the
// status palette is reserved for — and the legend below means hue never
// carries it alone.

const PAD = { top: 10, right: 10, bottom: 22, left: 34 };
const HEIGHT = 190;

interface Props {
  daily: StatsDailyPoint[];
}

function niceTicks(max: number): number[] {
  if (max <= 4) return [0, Math.max(1, max)];
  const step = Math.ceil(max / 3);
  return [0, step, step * 2, step * 3];
}

export default function RunsOverTimeChart({ daily }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const [width, setWidth] = useState(560);

  if (daily.length === 0) {
    return <div className="chart-empty">No runs recorded yet.</div>;
  }

  const innerW = Math.max(60, width - PAD.left - PAD.right);
  const innerH = HEIGHT - PAD.top - PAD.bottom;
  const ticks = niceTicks(Math.max(...daily.map((d) => d.runs), 1));
  const yMax = ticks[ticks.length - 1] || 1;

  // A single point has no span to divide; center it instead of dividing
  // by zero.
  const xAt = (i: number) => (daily.length === 1 ? innerW / 2 : (i / (daily.length - 1)) * innerW);
  const yAt = (v: number) => innerH - (v / yMax) * innerH;

  const path = (pick: (d: StatsDailyPoint) => number) =>
    daily
      .map((d, i) => `${i === 0 ? "M" : "L"}${xAt(i).toFixed(1)},${yAt(pick(d)).toFixed(1)}`)
      .join(" ");

  const active = hover === null ? null : (daily[hover] ?? null);
  // Sliced to MM-DD; both are present given the length guard above.
  const firstDate = daily[0]?.date.slice(5) ?? "";
  const lastDate = daily.length > 1 ? (daily[daily.length - 1]?.date.slice(5) ?? "") : "";

  return (
    <div>
      <div className="chart-legend" style={{ marginBottom: 6 }}>
        <span className="chart-legend__item">
          <span className="chart-legend__swatch" style={{ background: "var(--series-1)" }} />
          Total runs
        </span>
        <span className="chart-legend__item">
          <span className="chart-legend__swatch" style={{ background: "var(--status-critical)" }} />
          Failed runs
        </span>
      </div>

      <svg
        viewBox={`0 0 ${width} ${HEIGHT}`}
        width="100%"
        height={HEIGHT}
        role="img"
        aria-label="Runs and failed runs per day"
        ref={(node) => {
          const measured = node?.getBoundingClientRect().width;
          if (measured && Math.abs(measured - width) > 8) setWidth(measured);
        }}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(event) => {
          const box = event.currentTarget.getBoundingClientRect();
          const scale = width / box.width;
          const x = (event.clientX - box.left) * scale - PAD.left;
          const ratio = daily.length === 1 ? 0 : x / innerW;
          const index = Math.round(ratio * (daily.length - 1));
          setHover(Math.min(daily.length - 1, Math.max(0, index)));
        }}
      >
        <g transform={`translate(${PAD.left},${PAD.top})`}>
          {/* recessive gridlines + axis labels, never competing with the marks */}
          {ticks.map((t) => (
            <g key={t}>
              <line
                x1={0}
                y1={yAt(t)}
                x2={innerW}
                y2={yAt(t)}
                stroke="var(--grid)"
                strokeWidth="1"
              />
              <text
                x={-8}
                y={yAt(t)}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize="10"
                fill="var(--text-muted)"
              >
                {t}
              </text>
            </g>
          ))}

          {active && (
            <line
              x1={xAt(hover as number)}
              y1={0}
              x2={xAt(hover as number)}
              y2={innerH}
              stroke="var(--border-strong)"
              strokeWidth="1"
            />
          )}

          <path
            d={path((d) => d.runs)}
            fill="none"
            stroke="var(--series-1)"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d={path((d) => d.failed_runs)}
            fill="none"
            stroke="var(--status-critical)"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {active && hover !== null && (
            <>
              {/* 2px surface ring so an overlapping marker still reads as
                  two distinct marks, not one blob */}
              <circle
                cx={xAt(hover)}
                cy={yAt(active.runs)}
                r="4"
                fill="var(--series-1)"
                stroke="var(--surface-1)"
                strokeWidth="2"
              />
              <circle
                cx={xAt(hover)}
                cy={yAt(active.failed_runs)}
                r="4"
                fill="var(--status-critical)"
                stroke="var(--surface-1)"
                strokeWidth="2"
              />
            </>
          )}

          {/* first/last date only — a label per point collides at any real
              corpus size */}
          <text y={innerH + 15} fontSize="10" fill="var(--text-muted)">
            {firstDate}
          </text>
          {lastDate && (
            <text
              x={innerW}
              y={innerH + 15}
              textAnchor="end"
              fontSize="10"
              fill="var(--text-muted)"
            >
              {lastDate}
            </text>
          )}
        </g>
      </svg>

      <div style={{ minHeight: 18, fontSize: 12, color: "var(--text-secondary)" }}>
        {active ? (
          <>
            <span className="mono">{active.date}</span> · {active.runs} runs · {active.failed_runs}{" "}
            failed · ${active.cost_usd.toFixed(4)}
          </>
        ) : (
          <span className="muted">Hover the chart for a day&apos;s detail.</span>
        )}
      </div>
    </div>
  );
}
