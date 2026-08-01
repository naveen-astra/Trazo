import type { DetectionOut } from "../api/runApi";

// Severity is the dataviz skill's fixed status palette (never a
// categorical color, and never color alone -- the detector name is
// always the visible label next to it).
const SEVERITY_COLOR: Record<string, string> = {
  info: "var(--text-muted)",
  warn: "var(--status-warning)",
  critical: "var(--status-critical)",
};

function evidenceEventIds(detection: DetectionOut): string[] {
  return detection.evidence
    .map((entry) => entry.event_id)
    .filter((id): id is string => typeof id === "string");
}

interface DetectionBadgesProps {
  detections: DetectionOut[];
}

// TRZ-P5-06 DoD: "badge appears live during injected-loop smoke". One
// badge per raised detection; expanding it lists the evidence events,
// each linking straight to that event's spot in the timeline below
// (RunTimeline gives every event an `evt-{event_id}` DOM id for exactly
// this deep link).
export default function DetectionBadges({ detections }: DetectionBadgesProps) {
  if (detections.length === 0) {
    return null;
  }

  return (
    <div className="row" style={{ gap: 8 }}>
      {detections.map((detection) => {
        const color = SEVERITY_COLOR[detection.severity] ?? "var(--text-muted)";
        const evidence = evidenceEventIds(detection);
        return (
          <details key={detection.detection_id}>
            <summary className="badge" style={{ color, cursor: "pointer", listStyle: "none" }}>
              <span className="badge__dot" />
              {detection.detector}
              <span className="muted" style={{ fontWeight: 400 }}>
                {detection.severity}
              </span>
            </summary>
            {evidence.length > 0 && (
              <ul className="muted" style={{ margin: "6px 0 0", paddingLeft: 18, fontSize: 11.5 }}>
                {evidence.map((eventId) => (
                  <li key={eventId}>
                    <a href={`#evt-${eventId}`} className="mono">
                      {eventId}
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </details>
        );
      })}
    </div>
  );
}
