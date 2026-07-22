import { runStatusStyle } from "../lib/runStatus";

interface StatusBadgeProps {
  status: string;
}

/** Status color + text label together — never color alone (dataviz skill). */
export default function StatusBadge({ status }: StatusBadgeProps) {
  const style = runStatusStyle(status);
  return (
    <span className="status-badge" style={{ color: style.color, borderColor: style.color }}>
      <span className="status-badge__dot" style={{ background: style.color }} />
      {style.label}
    </span>
  );
}
