import { Link } from "react-router-dom";

import LiveBadge from "../components/LiveBadge";
import StatusBadge from "../components/StatusBadge";
import { useRuns } from "../hooks/useRuns";

function formatDuration(totals: Record<string, unknown>): string {
  const ms = totals.duration_ms;
  if (typeof ms !== "number") return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
}

function formatNumber(value: unknown): string {
  return typeof value === "number" ? String(value) : "—";
}

// Runs list (TRZ-P2-07): rollups + status + live badge, GET /v1/runs.
export default function RunsPage() {
  const { data, isLoading, isError, error } = useRuns();

  if (isLoading) {
    return (
      <div className="page">
        <p className="muted">Loading runs&hellip;</p>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="page">
        <p style={{ color: "var(--status-critical)" }}>
          Failed to load runs: {error instanceof Error ? error.message : String(error)}
        </p>
      </div>
    );
  }

  const runs = data?.runs ?? [];

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Runs</h1>
        <span className="page__sub">
          {runs.length} run{runs.length === 1 ? "" : "s"}
        </span>
      </div>

      <div className="card">
        {runs.length === 0 ? (
          <div className="empty-state">
            No runs yet. Instrument an agent with the SDK and run it to see it here.
          </div>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Run ID</th>
                  <th>Framework</th>
                  <th>Status</th>
                  <th className="table__num">Events</th>
                  <th className="table__num">LLM</th>
                  <th className="table__num">Tools</th>
                  <th className="table__num">Cost</th>
                  <th className="table__num">Duration</th>
                  <th>Started</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.run_id}>
                    <td>
                      <Link className="table__mono" to={`/runs/${run.run_id}`}>
                        {run.run_id}
                      </Link>
                    </td>
                    <td>{run.framework}</td>
                    <td>
                      <span className="row" style={{ gap: 6 }}>
                        <StatusBadge status={run.status} />
                        {run.status === "running" && <LiveBadge />}
                      </span>
                    </td>
                    <td className="table__num">{formatNumber(run.totals.events)}</td>
                    <td className="table__num">{formatNumber(run.totals.llm_calls)}</td>
                    <td className="table__num">{formatNumber(run.totals.tool_calls)}</td>
                    <td className="table__num">
                      {typeof run.totals.cost_usd === "number"
                        ? `$${run.totals.cost_usd.toFixed(2)}`
                        : "—"}
                    </td>
                    <td className="table__num">{formatDuration(run.totals)}</td>
                    <td className="muted">{new Date(run.started_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
