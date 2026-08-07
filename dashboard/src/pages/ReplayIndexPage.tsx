import { Link } from "react-router-dom";

import LiveBadge from "../components/LiveBadge";
import StatusBadge from "../components/StatusBadge";
import { useRuns } from "../hooks/useRuns";
import { useFilters } from "../lib/filters";

// Replay Studio needs a run to replay, so the nav entry lands here: pick
// one. Only finished runs are offered — a replay bundle is the record of
// a completed run, and re-driving one still in flight would race the
// events still being written.
export default function ReplayIndexPage() {
  const { project } = useFilters();
  const { data, isLoading } = useRuns(project ? { project } : {});

  const runs = (data?.runs ?? []).filter((run) => run.status !== "running");

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Replay Studio</h1>
        <span className="page__sub">pick a finished run to step through</span>
      </div>

      <div className="card">
        {isLoading && !data ? (
          <p className="muted">Loading runs&hellip;</p>
        ) : runs.length === 0 ? (
          <div className="empty-state">
            No finished runs to replay yet. <Link to="/runs">See all runs</Link>
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
                  <th>Started</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.run_id}>
                    <td className="table__mono">{run.run_id}</td>
                    <td>{run.framework}</td>
                    <td>
                      <span className="row" style={{ gap: 6 }}>
                        <StatusBadge status={run.status} />
                        {run.status === "running" && <LiveBadge />}
                      </span>
                    </td>
                    <td className="table__num">
                      {typeof run.totals.events === "number" ? run.totals.events : "—"}
                    </td>
                    <td className="muted">{new Date(run.started_at).toLocaleString()}</td>
                    <td>
                      <Link className="replay-btn" to={`/runs/${run.run_id}/replay`}>
                        Open
                      </Link>
                    </td>
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
