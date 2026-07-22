import { Link, useParams } from "react-router-dom";

import LiveBadge from "../components/LiveBadge";
import RunTimeline from "../components/RunTimeline";
import StatusBadge from "../components/StatusBadge";
import { useLiveRunEvents } from "../hooks/useLiveRunEvents";
import { useRun } from "../hooks/useRun";

// Run detail: kind-colored, step-grouped timeline (TRZ-P2-07). The event
// stream comes from useLiveRunEvents (GET /v1/live/runs/{id}), which
// covers both a finished run's full history and a running run's live
// tail in one mechanism (see that hook's docstring).
export default function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const { data: run, isLoading, isError, error } = useRun(runId ?? "");
  const { events, connected } = useLiveRunEvents(runId ?? "");

  if (!runId) {
    return <p>No run id.</p>;
  }

  return (
    <section>
      <p>
        <Link to="/">&larr; all runs</Link>
      </p>

      <div className="run-detail__header">
        <h1 style={{ fontFamily: "ui-monospace, monospace", fontSize: "1.1rem" }}>{runId}</h1>
        {run && <StatusBadge status={run.status} />}
        {run?.status === "running" && <LiveBadge />}
      </div>

      {isLoading && <p>Loading run&hellip;</p>}
      {isError && (
        <p style={{ color: "var(--status-critical)" }}>
          Failed to load run: {error instanceof Error ? error.message : String(error)}
        </p>
      )}

      {run && (
        <p style={{ color: "var(--text-secondary)", fontSize: "0.85rem", marginBottom: "1rem" }}>
          {run.framework} &middot; started {run.started_at}
          {run.finished_at ? ` · finished ${run.finished_at}` : ""}
          {!connected && events.length === 0 ? " · connecting…" : ""}
        </p>
      )}

      {events.length === 0 ? <p>No events yet.</p> : <RunTimeline events={events} />}
    </section>
  );
}
