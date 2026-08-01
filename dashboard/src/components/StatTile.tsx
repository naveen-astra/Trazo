import Sparkline from "./charts/Sparkline";

// A stat tile is the dataviz skill's "sometimes the answer is not a
// chart" case: one number, stated plainly, with an optional trend trace
// beside it. `trend` is omitted rather than faked for counters the API
// has no per-day series for (active runs, policy denials) — a flat or
// invented sparkline would imply history that was never measured.

interface StatTileProps {
  label: string;
  value: string;
  trend?: number[];
  trendColor?: string;
  foot?: string;
}

export default function StatTile({
  label,
  value,
  trend,
  trendColor = "var(--series-1)",
  foot,
}: StatTileProps) {
  return (
    <div className="stat">
      <span className="stat__label">{label}</span>
      <div className="stat__row">
        <span className="stat__value">{value}</span>
        {trend && trend.length > 1 && <Sparkline values={trend} color={trendColor} label={label} />}
      </div>
      {foot && <span className="stat__foot">{foot}</span>}
    </div>
  );
}
