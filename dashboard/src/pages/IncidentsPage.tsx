import { useState } from "react";
import { Link } from "react-router-dom";

import { IconAlert } from "../components/Icons";
import { useDetectionsFeed } from "../hooks/useCatalog";
import { useFilters } from "../lib/filters";

const SEVERITY_COLOR: Record<string, string> = {
  info: "var(--text-muted)",
  warn: "var(--status-warning)",
  critical: "var(--status-critical)",
};

// The known detector set (EVENTS.md's detection.raised.detector enum) —
// drift is listed there but has no implementation yet, so it will simply
// never match anything, same as any other detector with zero detections.
const DETECTOR_OPTIONS = ["loop", "budget", "thrash", "drift"];
const SEVERITY_OPTIONS = ["info", "warn", "critical"];
const FEED_LIMIT = 100;

// Fleet-wide detection feed, GET /v1/detections — distinct from the
// Overview's mini-widget (StatsOut.recent_detections, fixed at 8): this
// page's whole job is incident review, so it needs more rows and real
// filters, which is exactly what /v1/detections adds over reusing /v1/stats.
export default function IncidentsPage() {
  const { project } = useFilters();
  const [detector, setDetector] = useState("");
  const [severity, setSeverity] = useState("");
  const { data, isLoading, isError, error } = useDetectionsFeed({
    project: project || undefined,
    detector: detector || undefined,
    severity: severity || undefined,
    limit: FEED_LIMIT,
  });

  if (isLoading && !data) {
    return (
      <div className="page">
        <p className="muted">Loading incidents&hellip;</p>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="page">
        <p style={{ color: "var(--status-critical)" }}>
          Failed to load incidents: {error instanceof Error ? error.message : String(error)}
        </p>
      </div>
    );
  }

  const detections = data.detections;

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Incidents</h1>
        <span className="page__sub">
          {detections.length} detection{detections.length === 1 ? "" : "s"}, newest first
        </span>
        <span style={{ marginLeft: "auto" }} />
        <label className="select-wrap select-wrap--sm">
          <select
            className="select select--sm"
            value={detector}
            onChange={(event) => setDetector(event.target.value)}
          >
            <option value="">All detectors</option>
            {DETECTOR_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label className="select-wrap select-wrap--sm">
          <select
            className="select select--sm"
            value={severity}
            onChange={(event) => setSeverity(event.target.value)}
          >
            <option value="">All severities</option>
            {SEVERITY_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
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
