import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { listRuns, type RunOut } from "../api/runApi";
import LiveBadge from "../components/LiveBadge";
import StatusBadge from "../components/StatusBadge";
import { useProjectName } from "../hooks/useCatalog";
import { useRuns } from "../hooks/useRuns";
import { useFilters } from "../lib/filters";

// The real run.finished status enum (EVENTS.md) plus "running"/"stale"
// (RunRow.status) — not invented values.
const STATUS_OPTIONS = ["running", "ok", "error", "blocked", "cancelled", "stale"];

function formatDuration(totals: Record<string, unknown>): string {
  const ms = totals.duration_ms;
  if (typeof ms !== "number") return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
}

function formatNumber(value: unknown): string {
  return typeof value === "number" ? String(value) : "—";
}

// Runs list (TRZ-P2-07): rollups + status + live badge, GET /v1/runs, now
// wired to the shared project filter, a status filter, and "Load more"
// pagination via the API's own cursor (both existed server-side and were
// never consumed here). The first page stays on the live, SSE-refreshed
// `useRuns` query; pages beyond that are fetched imperatively and
// appended — keeping the live page live while "more" stays static until
// the filters change is simpler than trying to make the whole
// accumulated list re-fetch coherently. No client-side sort: with
// pagination in play, a sort would silently only reorder whatever page
// happens to be loaded.
export default function RunsPage() {
  const { project } = useFilters();
  const [status, setStatus] = useState<string>("");
  const [extraRuns, setExtraRuns] = useState<RunOut[]>([]);
  // null = "haven't paginated yet, follow the live first page's cursor";
  // a string/undefined past that point is owned by loadMore, so a live
  // SSE refresh of page 1 can't quietly reset how far the user has paged.
  const [manualCursor, setManualCursor] = useState<string | null | undefined>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const projectName = useProjectName();

  const { data, isLoading, isError, error } = useRuns({
    project: project || undefined,
    status: status || undefined,
  });

  // Filters changed: the accumulated "more" pages belong to the old
  // filter and must not linger under the new one.
  useEffect(() => {
    setExtraRuns([]);
    setManualCursor(null);
  }, [project, status]);

  const nextCursor = manualCursor !== null ? manualCursor : data?.next_cursor;

  async function loadMore() {
    if (!nextCursor) return;
    setLoadingMore(true);
    try {
      const page = await listRuns({
        project: project || undefined,
        status: status || undefined,
        cursor: nextCursor,
      });
      setExtraRuns((prev) => [...prev, ...page.runs]);
      setManualCursor(page.next_cursor ?? undefined);
    } finally {
      setLoadingMore(false);
    }
  }

  if (isLoading && !data) {
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

  // De-duped by run_id: page 1 keeps refreshing live off the head of the
  // list while extraRuns is a static snapshot from further back, so a run
  // near the page-1/page-2 boundary can legitimately appear in both after
  // new runs shift the keyset window.
  const seen = new Set<string>();
  const runs = [...(data?.runs ?? []), ...extraRuns].filter((run) => {
    if (seen.has(run.run_id)) return false;
    seen.add(run.run_id);
    return true;
  });

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Runs</h1>
        <span className="page__sub">
          {runs.length} run{runs.length === 1 ? "" : "s"}
        </span>
        <span style={{ marginLeft: "auto" }} />
        <label className="select-wrap select-wrap--sm">
          <select
            className="select select--sm"
            value={status}
            onChange={(event) => setStatus(event.target.value)}
          >
            <option value="">All statuses</option>
            {STATUS_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
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
                  <th>Project</th>
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
                    <td className="muted">{projectName(run.project_id)}</td>
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

      {nextCursor && (
        <button
          type="button"
          className="replay-btn"
          onClick={() => void loadMore()}
          disabled={loadingMore}
        >
          {loadingMore ? "Loading…" : "Load more"}
        </button>
      )}
    </div>
  );
}
