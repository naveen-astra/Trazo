// Run-status presentation (TRZ-P2-07). Status colors are the dataviz
// skill's fixed, never-themed status palette — reserved for exactly this
// (a state), never reused as a categorical series color. Always paired
// with the visible text label (never color alone).
export type RunStatus = "running" | "ok" | "error" | "blocked" | "cancelled" | "stale";

interface StatusStyle {
  color: string;
  label: string;
}

const STATUS_STYLE: Record<RunStatus, StatusStyle> = {
  running: { color: "var(--text-muted)", label: "running" },
  ok: { color: "var(--status-good)", label: "ok" },
  error: { color: "var(--status-critical)", label: "error" },
  blocked: { color: "var(--status-warning)", label: "blocked" },
  stale: { color: "var(--status-warning)", label: "stale" },
  cancelled: { color: "var(--text-muted)", label: "cancelled" },
};

export function runStatusStyle(status: string): StatusStyle {
  return STATUS_STYLE[status as RunStatus] ?? { color: "var(--text-muted)", label: status };
}
