import { Link } from "react-router-dom";

import { IconAlert } from "../components/Icons";
import { useStats } from "../hooks/useStats";

const SEVERITY_COLOR: Record<string, string> = {
  info: "var(--text-muted)",
  warn: "var(--status-warning)",
  critical: "var(--status-critical)",
};

// Fleet-wide detection feed, straight off GET /v1/stats' cross-run
// `recent_detections` (the same feed the Overview card shows). Bounded
// to the newest N by the endpoint itself rather than paginated: an
// incident feed answers "what is going wrong now", and older detections
// are reachable per-run from that run's own page.
export default function IncidentsPage() {
  const { data: stats, isLoading, isError, error } = useStats();

  if (isLoading) {
    return (
      <div className="page">
        <p className="muted">Loading incidents&hellip;</p>
      </div>
    );
  }

  if (isError || !stats) {
    return (
      <div className="page">
        <p style={{ color: "var(--status-critical)" }}>
          Failed to load incidents: {error instanceof Error ? error.message : String(error)}
        </p>
      </div>
    );
  }

  const detections = stats.recent_detections;

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Incidents</h1>
        <span className="page__sub">detections raised across every run, newest first</span>
      </div>

      <div className="card">
        {detections.length === 0 ? (
          <div className="empty-state">
            No detections raised. The loop, budget, and thrash detectors run over every event as it
            arrives.
          </div>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Detector</th>
                  <th>Severity</th>
                  <th>Run</th>
                  <th className="table__num">Evidence</th>
                  <th>Raised</th>
                </tr>
              </thead>
              <tbody>
                {detections.map((detection) => (
                  <tr key={detection.detection_id}>
                    <td>
                      <span
                        className="row"
                        style={{
                          gap: 7,
                          color: SEVERITY_COLOR[detection.severity],
                        }}
                      >
                        <IconAlert size={14} />
                        <span style={{ color: "var(--text-primary)", fontWeight: 550 }}>
                          {detection.detector}
                        </span>
                      </span>
                    </td>
                    <td>
                      <span
                        className="badge"
                        style={{
                          color: SEVERITY_COLOR[detection.severity] ?? "var(--text-muted)",
                        }}
                      >
                        <span className="badge__dot" />
                        {detection.severity}
                      </span>
                    </td>
                    <td>
                      <Link className="table__mono" to={`/runs/${detection.run_id}`}>
                        {detection.run_id}
                      </Link>
                    </td>
                    <td className="table__num">{detection.evidence.length}</td>
                    <td className="muted">{new Date(detection.raised_at).toLocaleString()}</td>
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
