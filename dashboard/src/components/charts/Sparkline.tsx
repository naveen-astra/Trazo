// Trend sparkline for a stat tile: one series, no axes, no legend (a
// single series needs none — the tile's label names it). Hand-rolled SVG
// rather than a charting dependency; the whole shape is a polyline.
//
// No hover layer here on purpose. The dataviz skill wants one on any
// real plot, but this is the supporting half of a stat tile whose hero
// number already states the current value exactly — a tooltip on a 64px
// trace would restate it less legibly. The tile carries the number; the
// sparkline carries only the shape of how it got there.

interface SparklineProps {
  values: number[];
  color: string;
  width?: number;
  height?: number;
  label: string;
}

export default function Sparkline({
  values,
  color,
  width = 74,
  height = 28,
  label,
}: SparklineProps) {
  if (values.length < 2) {
    return <svg width={width} height={height} aria-hidden />;
  }

  const max = Math.max(...values);
  const min = Math.min(...values);
  const span = max - min || 1;
  // Inset by the stroke's half-width so the 2px line never clips at the
  // top/bottom edge of the viewBox.
  const pad = 2;
  const stepX = width / (values.length - 1);

  const points = values.map((value, i) => {
    const x = i * stepX;
    const y = pad + (1 - (value - min) / span) * (height - pad * 2);
    return [x, y] as const;
  });

  const line = points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${line} ${width},${height} 0,${height}`;
  const gradientId = `spark-${label.replace(/\W+/g, "-")}`;
  // Non-empty by the length guard above; the fallback only satisfies the
  // compiler's index check.
  const [lastX, lastY] = points[points.length - 1] ?? [0, 0];

  return (
    <svg
      width={width}
      height={height}
      role="img"
      aria-label={`${label} trend`}
      className="stat__spark"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.28" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={area} fill={`url(#${gradientId})`} />
      <polyline
        points={line}
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* the current value gets the one marker — selective, not a dot per point */}
      <circle cx={lastX} cy={lastY} r="2.5" fill={color} />
    </svg>
  );
}
