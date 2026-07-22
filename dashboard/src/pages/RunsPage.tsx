import { Link } from "react-router-dom";

import LiveBadge from "../components/LiveBadge";
import StatusBadge from "../components/StatusBadge";
import { useRuns } from "../hooks/useRuns";

// Runs list (TRZ-P2-07): rollups + status + live badge, GET /v1/runs.
export default function RunsPage() {
  const { data, isLoading, isError, error } = useRuns();

  if (isLoading) {
    return (
      <section>
        <h1>Runs</h1>
        <p>Loading&hellip;</p>
      </section>
    );
  }

  if (isError) {
    return (
      <section>
        <h1>Runs</h1>
        <p style={{ color: "var(--status-critical)" }}>
          Failed to load runs: {error instanceof Error ? error.message : String(error)}
        </p>
      </section>
    );
  }

  const runs = data?.runs ?? [];

  return (
    <section>
      <h1>Runs</h1>
      {runs.length === 0 ? (
        <p>No runs yet. Instrument an agent with the SDK and run it to see it here.</p>
      ) : (
        <ul className="runs-list">
          {runs.map((run) => (
            <li key={run.run_id}>
              <Link className="run-row" to={`/runs/${run.run_id}`}>
                <span className="run-row__id">{run.run_id}</span>
                <span className="run-row__framework">{run.framework}</span>
                <StatusBadge status={run.status} />
                {run.status === "running" && <LiveBadge />}
                <span className="run-row__spacer" />
                <span className="run-row__totals">
                  {typeof run.totals.events === "number" ? `${run.totals.events} events` : null}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
