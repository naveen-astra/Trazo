import type { PolicyDecisionOut } from "../api/runApi";

// Decision value is the dataviz skill's fixed status palette (never a
// categorical color, never color alone -- the decision word itself is
// always the visible label next to it).
const DECISION_COLOR: Record<string, string> = {
  allow: "var(--status-good)",
  escalate: "var(--status-warning)",
  deny: "var(--status-critical)",
};

interface PolicyDecisionsPanelProps {
  decisions: PolicyDecisionOut[];
}

// TRZ-P6-05 DoD: "Deny visible in UI with policy id + reasons". Reasons
// are always shown inline (not behind a disclosure toggle, unlike
// DetectionBadges' evidence list) -- a deny/escalate is exactly the
// moment a reader needs the "why" without an extra click.
export default function PolicyDecisionsPanel({ decisions }: PolicyDecisionsPanelProps) {
  if (decisions.length === 0) {
    return null;
  }

  return (
    <div className="card">
      <div className="card__head">
        <h2 className="card__title">Policy decisions</h2>
        <span className="muted" style={{ fontSize: 12 }}>
          {decisions.length}
        </span>
      </div>
      <div className="stack" style={{ gap: 8 }}>
        {decisions.map((decision) => {
          const color = DECISION_COLOR[decision.decision] ?? "var(--text-muted)";
          return (
            <div
              key={decision.decision_id}
              style={{
                borderLeft: `2px solid ${color}`,
                paddingLeft: 10,
              }}
            >
              <div className="row" style={{ gap: 8 }}>
                <span className="badge" style={{ color }}>
                  <span className="badge__dot" />
                  {decision.decision}
                </span>
                <span style={{ fontWeight: 550 }}>{decision.policy_id}</span>
                <span className="muted mono" style={{ fontSize: 12 }}>
                  {decision.action_kind}
                </span>
              </div>
              {decision.reasons.length > 0 && (
                <ul
                  className="muted"
                  style={{ margin: "4px 0 0", paddingLeft: 18, fontSize: 12.5 }}
                >
                  {decision.reasons.map((reason, index) => (
                    <li key={index}>{reason}</li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
