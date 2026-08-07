import Sparkline from "./charts/Sparkline";

// A stat tile is the dataviz skill's "sometimes the answer is not a
// chart" case: one number, stated plainly, with an optional trend trace
// and period-over-period delta beside it.
//
// `trend` and `delta` are each omitted rather than faked when the API
// has nothing behind them — a flat sparkline or a 0% delta would imply
// history that was never measured. `delta === null` specifically means
// "no prior window to compare against", which the tile says in words.

interface StatTileProps {
  label: string;
  value: string;
  trend?: number[];
  trendColor?: string;
  /** Percent change vs the previous equal-length window; null = no baseline. */
  delta?: number | null;
  /** Whether a rise is good news — flips the delta's status color. */
  riseIsGood?: boolean;
  foot?: string;
}

export default function StatTile({
  label,
  value,
  trend,
  trendColor = "var(--series-1)",
  delta,
  riseIsGood = true,
  foot,
}: StatTileProps) {
  const hasDelta = delta !== undefined && delta !== null && Number.isFinite(delta);
  const rising = hasDelta && (delta as number) > 0;
  const flat = hasDelta && (delta as number) === 0;
  const deltaColor = flat
    ? "var(--text-muted)"
    : rising === riseIsGood
      ? "var(--status-good)"
      : "var(--status-critical)";

  return (
    <div className="stat">
      <span className="stat__label">{label}</span>
      <div className="stat__row">
        <span className="stat__value">{value}</span>
        {trend && trend.length > 1 && <Sparkline values={trend} color={trendColor} label={label} />}
      </div>
      {hasDelta ? (
        <span className="stat__foot" style={{ color: deltaColor }}>
          {/* Arrow + sign + the words "vs previous" — direction never
              rides on color alone. */}
          {rising ? "▲" : flat ? "■" : "▼"} {Math.abs(delta as number).toFixed(1)}% vs previous
        </span>
      ) : (
        foot && <span className="stat__foot">{foot}</span>
      )}
    </div>
  );
}
