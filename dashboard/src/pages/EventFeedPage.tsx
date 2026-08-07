import { Link } from "react-router-dom";

import { eventKindChipColor } from "../lib/eventKind";
import { useRecentEvents } from "../hooks/useCatalog";

interface Props {
  /** Narrow the feed to one event kind (the Logs route passes
   * "sdk.diagnostic"); omitted shows the whole trace stream. */
  kind?: string;
  title: string;
  subtitle: string;
  emptyMessage: React.ReactNode;
}

/** Shared body for Traces and Logs: both are "newest events across every
 * run", differing only by kind filter, so they share one component
 * rather than two near-identical pages that could drift apart. */
export default function EventFeedPage({ kind, title, subtitle, emptyMessage }: Props) {
  const { data, isLoading, isError, error } = useRecentEvents({ kind, limit: 200 });

  if (isLoading && !data) {
    return (
      <div className="page">
        <p className="muted">Loading&hellip;</p>
      </div>
    );
  }
  if (isError || !data) {
    return (
      <div className="page">
        <p style={{ color: "var(--status-critical)" }}>
          Failed to load: {error instanceof Error ? error.message : String(error)}
        </p>
      </div>
    );
  }

  const events = data.events;

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">{title}</h1>
        <span className="page__sub">{subtitle}</span>
      </div>

      <div className="card">
        {events.length === 0 ? (
          <div className="empty-state">{emptyMessage}</div>
        ) : (
          <div className="table-scroll table-scroll--tall">
            <table className="table">
              <thead>
                <tr>
                  <th>Kind</th>
                  <th>Run</th>
                  <th className="table__num">Seq</th>
                  <th>Fingerprint</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => {
                  const color = eventKindChipColor(event.kind);
                  return (
                    <tr key={event.event_id}>
                      <td>
                        <span className="row" style={{ gap: 7 }}>
                          <span
                            className="chip__dot"
                            style={
                              color
                                ? { background: color }
                                : { border: "1px solid var(--text-muted)" }
                            }
                          />
                          <span className="mono" style={{ color: "var(--text-primary)" }}>
                            {event.kind}
                          </span>
                        </span>
                      </td>
                      <td>
                        <Link className="table__mono" to={`/runs/${event.run_id}`}>
                          {event.run_id.slice(0, 20)}…
                        </Link>
                      </td>
                      <td className="table__num">{event.seq}</td>
                      <td className="muted mono" style={{ fontSize: 11 }}>
                        {event.fingerprint ? `${event.fingerprint.slice(7, 21)}…` : "—"}
                      </td>
                      <td className="muted">{new Date(event.ts).toLocaleString()}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
