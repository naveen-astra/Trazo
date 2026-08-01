import { runStatusStyle } from "../lib/runStatus";

interface StatusBadgeProps {
  status: string;
}

/** Status color + text label together — never color alone (dataviz skill). */
export default function StatusBadge({ status }: StatusBadgeProps) {
  const style = runStatusStyle(status);
  return (
    <span className="badge" style={{ color: style.color }}>
      <span className="badge__dot" />
      {style.label}
    </span>
  );
}
