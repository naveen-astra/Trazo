import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { usePolicyDecisionsFeed } from "../hooks/useCatalog";
import { useFilters } from "../lib/filters";

// Decision colors are the fixed status palette: deny/escalate are states
// (blocked, needs-a-human), never categorical series identity — and the
// decision word itself is always the visible label beside the color.
const DECISION_COLOR: Record<string, string> = {
  allow: "var(--status-good)",
  deny: "var(--status-critical)",
  escalate: "var(--status-warning)",
};
const DECISION_OPTIONS = ["allow", "deny", "escalate"];
const FEED_LIMIT = 100;

// Fleet-wide policy-decision feed, GET /v1/policy-decisions — distinct
// from the Overview's mini-widget (StatsOut.recent_policy_decisions,
// fixed at 12): this page needs enough rows and real filters to actually
// audit governance activity, which reusing /v1/stats never gave it.
export default function PolicyPage() {
  const { project } = useFilters();
  const [decision, setDecision] = useState("");
  const [policyId, setPolicyId] = useState("");
  const { data, isLoading, isError, error } = usePolicyDecisionsFeed({
    project: project || undefined,
    decision: decision || undefined,
    policyId: policyId || undefined,
    limit: FEED_LIMIT,
  });

  // Policy ids are arbitrary (defined by whatever .rego bundles are
  // loaded), so there's no fixed enum to offer — populate the filter
  // from what this page has actually seen, same as any faceted search.
  const policyIdOptions = useMemo(() => {
    const ids = new Set((data?.decisions ?? []).map((d) => d.policy_id));
    return [...ids].sort();
  }, [data]);

  if (isLoading && !data) {
    return (
      <div className="page">
        <p className="muted">Loading policy decisions&hellip;</p>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="page">
        <p style={{ color: "var(--status-critical)" }}>
          Failed to load policy decisions: {error instanceof Error ? error.message : String(error)}
        </p>
      </div>
    );
  }

  const decisions = data.decisions;
  const denialCount = decisions.filter(
    (d) => d.decision === "deny" || d.decision === "escalate",
  ).length;

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Policy</h1>
        <span className="page__sub">
          {denialCount} denial{denialCount === 1 ? "" : "s"} of {decisions.length} shown
        </span>
        <span style={{ marginLeft: "auto" }} />
        <label className="select-wrap select-wrap--sm">
          <select
            className="select select--sm"
            value={decision}
            onChange={(event) => setDecision(event.target.value)}
          >
            <option value="">All decisions</option>
            {DECISION_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label className="select-wrap select-wrap--sm">
          <select
            className="select select--sm"
            value={policyId}
            onChange={(event) => setPolicyId(event.target.value)}
          >
            <option value="">All policies</option>
            {policyIdOptions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
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
                {decisions.map((d) => (
                  <tr key={d.decision_id}>
                    <td>
                      <span
                        className="badge"
                        style={{
                          color: DECISION_COLOR[d.decision] ?? "var(--text-muted)",
                        }}
                      >
                        <span className="badge__dot" />
                        {d.decision}
                      </span>
                    </td>
                    <td style={{ color: "var(--text-primary)" }}>{d.policy_id || "—"}</td>
                    <td className="mono" style={{ fontSize: 12 }}>
                      {d.action_kind}
                    </td>
                    <td>
                      {d.reasons.length === 0 ? (
                        <span className="muted">—</span>
                      ) : (
                        d.reasons.join("; ")
                      )}
                    </td>
                    <td>
                      <Link className="table__mono" to={`/runs/${d.run_id}`}>
                        {d.run_id}
                      </Link>
                    </td>
                    <td>{d.mode}</td>
                    <td className="table__num">{d.eval_ms.toFixed(0)}ms</td>
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
