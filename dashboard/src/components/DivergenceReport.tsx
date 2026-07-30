// Matches trazo verify <run_id> --json's exact output shape
// (sdk/src/trazo/cli/replay.py's _report_summary/_divergence_summary) --
// hand-written here for the same reason ReplayBundle is in runApi.ts: no
// HTTP endpoint serves this today (a replay session runs inside the
// SDK's own Python process, not behind FastAPI), so there's no OpenAPI
// schema to generate a type from.
export interface DivergenceDetail {
  kind: string;
  reason: string;
  expected_seq: number | null;
  expected_event_id: string | null;
  expected_fingerprint: string | null;
  live_fingerprint: string;
}

export interface DivergenceReportData {
  boundary_fidelity: number;
  state_fidelity: number;
  matched: number;
  reordered: number;
  divergences: DivergenceDetail[];
  replay_overhead?: number | null;
}

interface DivergenceReportProps {
  report: DivergenceReportData;
}

/** TRZ-P6-07 DoD: "renders a divergence report fixture" -- the fidelity
 * headline (REPLAY_ENGINE.md §5) plus every divergence's expected-vs-live
 * fingerprint, the exact thing a reader debugging a broken replay needs. */
export default function DivergenceReport({ report }: DivergenceReportProps) {
  const hasDivergences = report.divergences.length > 0;

  return (
    <div className="divergence-report">
      <dl className="divergence-report__summary">
        <div>
          <dt>boundary fidelity</dt>
          <dd>{(report.boundary_fidelity * 100).toFixed(1)}%</dd>
        </div>
        <div>
          <dt>state fidelity</dt>
          <dd>{(report.state_fidelity * 100).toFixed(1)}%</dd>
        </div>
        <div>
          <dt>matched</dt>
          <dd>{report.matched}</dd>
        </div>
        <div>
          <dt>reordered</dt>
          <dd>{report.reordered}</dd>
        </div>
        {report.replay_overhead != null && (
          <div>
            <dt>replay overhead</dt>
            <dd>{report.replay_overhead.toFixed(2)}x</dd>
          </div>
        )}
      </dl>

      {hasDivergences ? (
        <ul className="divergence-report__list">
          {report.divergences.map((divergence, index) => (
            <li key={index} className="divergence-report__item">
              <div className="divergence-report__item-header">
                <span className="divergence-report__kind">{divergence.kind}</span>
                <span>{divergence.reason}</span>
              </div>
              <dl className="divergence-report__fingerprints">
                <div>
                  <dt>expected</dt>
                  <dd>
                    seq {divergence.expected_seq ?? "—"} · event{" "}
                    {divergence.expected_event_id ?? "—"}
                    <br />
                    {divergence.expected_fingerprint ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt>live</dt>
                  <dd>{divergence.live_fingerprint}</dd>
                </div>
              </dl>
            </li>
          ))}
        </ul>
      ) : (
        <p style={{ color: "var(--status-good)" }}>no divergences</p>
      )}
    </div>
  );
}
