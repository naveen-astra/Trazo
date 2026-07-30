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
    <div className="policy-decisions">
      <h2 className="policy-decisions__heading">Policy decisions</h2>
      <ul className="policy-decisions__list">
        {decisions.map((decision) => {
          const color = DECISION_COLOR[decision.decision] ?? "var(--text-muted)";
          return (
            <li
              key={decision.decision_id}
              className="policy-decision"
              style={{ borderColor: color }}
            >
              <div className="policy-decision__header">
                <span className="policy-decision__dot" style={{ background: color }} />
                <span className="policy-decision__decision" style={{ color }}>
                  {decision.decision}
                </span>
                <span className="policy-decision__policy-id">{decision.policy_id}</span>
                <span className="policy-decision__action-kind">{decision.action_kind}</span>
              </div>
              {decision.reasons.length > 0 && (
                <ul className="policy-decision__reasons">
                  {decision.reasons.map((reason, index) => (
                    <li key={index}>{reason}</li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
