import { Link } from "react-router-dom";

import { useStats } from "../hooks/useStats";

// Decision colors are the fixed status palette: deny/escalate are states
// (blocked, needs-a-human), never categorical series identity — and the
// decision word itself is always the visible label beside the color.
const DECISION_COLOR: Record<string, string> = {
  allow: "var(--status-good)",
  deny: "var(--status-critical)",
  escalate: "var(--status-warning)",
};

export default function PolicyPage() {
  const { data: stats, isLoading, isError, error } = useStats();

  if (isLoading) {
    return (
      <div className="page">
        <p className="muted">Loading policy decisions&hellip;</p>
      </div>
    );
  }

  if (isError || !stats) {
    return (
      <div className="page">
        <p style={{ color: "var(--status-critical)" }}>
          Failed to load policy decisions: {error instanceof Error ? error.message : String(error)}
        </p>
      </div>
    );
  }

  const decisions = stats.recent_policy_decisions;

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Policy</h1>
        <span className="page__sub">
          {stats.policy_denials} denial{stats.policy_denials === 1 ? "" : "s"} in the recent
          decision window
        </span>
      </div>

      <div className="card">
        {decisions.length === 0 ? (
          <div className="empty-state">
            No policy decisions recorded. The SDK evaluates a policy synchronously before every
            governed action — set <code className="mono">TRAZO_POLICY_MODE=enforce</code> to turn
            enforcement on.
          </div>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Decision</th>
                  <th>Policy</th>
                  <th>Action</th>
                  <th>Reasons</th>
                  <th>Run</th>
                  <th>Mode</th>
                  <th className="table__num">Eval</th>
                </tr>
              </thead>
              <tbody>
                {decisions.map((decision) => (
                  <tr key={decision.decision_id}>
                    <td>
                      <span
                        className="badge"
                        style={{
                          color: DECISION_COLOR[decision.decision] ?? "var(--text-muted)",
                        }}
                      >
                        <span className="badge__dot" />
                        {decision.decision}
                      </span>
                    </td>
                    <td style={{ color: "var(--text-primary)" }}>{decision.policy_id || "—"}</td>
                    <td className="mono" style={{ fontSize: 12 }}>
                      {decision.action_kind}
                    </td>
                    <td>
                      {decision.reasons.length === 0 ? (
                        <span className="muted">—</span>
                      ) : (
                        decision.reasons.join("; ")
                      )}
                    </td>
                    <td>
                      <Link className="table__mono" to={`/runs/${decision.run_id}`}>
                        {decision.run_id.slice(0, 18)}…
                      </Link>
                    </td>
                    <td>{decision.mode}</td>
                    <td className="table__num">{decision.eval_ms.toFixed(0)}ms</td>
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
