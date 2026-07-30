import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { BlobField } from "../components/PayloadDrawer";
import DivergenceReport from "../components/DivergenceReport";
import { eventKindChipColor } from "../lib/eventKind";
import { isBlobRef, type EventOut } from "../api/runApi";
import { useReplayBundle } from "../hooks/useReplayBundle";
import sampleDivergenceReport from "../replayFixtures/sample-divergence-report.json";

interface Step {
  stepId: string;
  stepName: string | null;
  stepIndex: number;
  stateBefore: unknown;
  stateAfter: unknown;
  boundaryEvents: EventOut[];
}

const _BOUNDARY_KINDS = new Set([
  "llm.call",
  "tool.call",
  "memory.read",
  "memory.write",
  "human.checkpoint",
]);

// Positional, not step_id-keyed: verified directly against a real
// recorded bundle that the LangGraph adapter's own llm.call/tool.call/
// memory.* events carry step_id: null in practice (only step.started/
// step.finished themselves carry a real one) -- grouping by matching
// step_id would silently leave every step's boundary-call list empty.
// Walking events in seq order and attributing each boundary call to
// whichever step.started is currently open works regardless of that,
// and matches how a reader scans the timeline anyway.
function groupIntoSteps(events: EventOut[]): Step[] {
  const steps: Step[] = [];
  let current: Step | null = null;

  for (const event of events) {
    if (event.kind === "step.started") {
      const payload = event.payload as Record<string, unknown>;
      current = {
        stepId: event.step_id ?? event.event_id,
        stepName: typeof payload.name === "string" ? payload.name : null,
        stepIndex: steps.length,
        stateBefore: payload.state_before,
        stateAfter: undefined,
        boundaryEvents: [],
      };
      steps.push(current);
    } else if (event.kind === "step.finished") {
      if (current) {
        const payload = event.payload as Record<string, unknown>;
        current.stateAfter = payload.state_after;
      }
    } else if (_BOUNDARY_KINDS.has(event.kind) && current) {
      current.boundaryEvents.push(event);
    }
  }

  return steps;
}

interface StateDiffEntry {
  key: string;
  status: "added" | "removed" | "changed" | "unchanged";
  before: unknown;
  after: unknown;
}

// A flat, top-level-key diff -- enough for typical agent state dicts
// (a handful of top-level fields); not a recursive/structural diff.
function diffState(before: unknown, after: unknown): StateDiffEntry[] {
  const beforeObj = (before && typeof before === "object" ? before : {}) as Record<string, unknown>;
  const afterObj = (after && typeof after === "object" ? after : {}) as Record<string, unknown>;
  const keys = [...new Set([...Object.keys(beforeObj), ...Object.keys(afterObj)])].sort();

  return keys.map((key) => {
    const hasBefore = key in beforeObj;
    const hasAfter = key in afterObj;
    const beforeVal = beforeObj[key];
    const afterVal = afterObj[key];
    let status: StateDiffEntry["status"] = "unchanged";
    if (!hasBefore) status = "added";
    else if (!hasAfter) status = "removed";
    else if (JSON.stringify(beforeVal) !== JSON.stringify(afterVal)) status = "changed";
    return { key, status, before: beforeVal, after: afterVal };
  });
}

function StateSide({ label, state }: { label: string; state: unknown }) {
  if (isBlobRef(state)) {
    return (
      <div>
        <h4>{label}</h4>
        <BlobField field={label} sha256={state.$blob} />
      </div>
    );
  }
  return (
    <div>
      <h4>{label}</h4>
      <pre className="replay-stepper__state-json">{JSON.stringify(state, null, 2)}</pre>
    </div>
  );
}

function StepStateDiff({ step }: { step: Step }) {
  if (isBlobRef(step.stateBefore) || isBlobRef(step.stateAfter)) {
    return (
      <div className="replay-stepper__state">
        <StateSide label="before" state={step.stateBefore} />
        <StateSide label="after" state={step.stateAfter} />
      </div>
    );
  }

  const entries = diffState(step.stateBefore, step.stateAfter);
  return (
    <table className="replay-stepper__diff-table">
      <thead>
        <tr>
          <th>key</th>
          <th>before</th>
          <th>after</th>
        </tr>
      </thead>
      <tbody>
        {entries.map((entry) => (
          <tr key={entry.key} className={`replay-diff-row replay-diff-row--${entry.status}`}>
            <td>{entry.key}</td>
            <td>
              <pre>{JSON.stringify(entry.before, null, 2)}</pre>
            </td>
            <td>
              <pre>{JSON.stringify(entry.after, null, 2)}</pre>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// TRZ-P6-07: bundle-driven step list, state before/after diff, boundary
// events inline. Fetches the same replay bundle the SDK's own
// trazo.replay driver would (GET /runs/{id}/replay-bundle) and walks it
// entirely client-side -- no live replay session runs here (that's the
// SDK's job, in its own Python process); this is a read-only viewer over
// what a bundle already records.
export default function ReplayStepperPage() {
  const { runId } = useParams<{ runId: string }>();
  const { data: bundle, isLoading, isError, error } = useReplayBundle(runId ?? "");
  const [selectedIndex, setSelectedIndex] = useState(0);

  if (!runId) {
    return <p>No run id.</p>;
  }

  const steps = bundle ? groupIntoSteps(bundle.events) : [];
  const selectedStep = steps[selectedIndex];

  return (
    <section>
      <p>
        <Link to={`/runs/${runId}`}>&larr; back to run</Link>
      </p>
      <h1 style={{ fontFamily: "ui-monospace, monospace", fontSize: "1.1rem" }}>replay: {runId}</h1>

      {isLoading && <p>Loading replay bundle&hellip;</p>}
      {isError && (
        <p style={{ color: "var(--status-critical)" }}>
          Failed to load replay bundle: {error instanceof Error ? error.message : String(error)}
        </p>
      )}

      {steps.length === 0 && bundle && <p>No steps recorded for this run.</p>}

      {steps.length > 0 && (
        <div className="replay-stepper">
          <nav className="replay-stepper__steps">
            {steps.map((step, index) => (
              <button
                key={step.stepId}
                type="button"
                className={
                  index === selectedIndex
                    ? "replay-stepper__step replay-stepper__step--selected"
                    : "replay-stepper__step"
                }
                onClick={() => setSelectedIndex(index)}
              >
                #{step.stepIndex} {step.stepName ?? step.stepId}
              </button>
            ))}
          </nav>

          {selectedStep && (
            <div className="replay-stepper__detail">
              <h3>
                step #{selectedStep.stepIndex} &middot;{" "}
                {selectedStep.stepName ?? selectedStep.stepId}
              </h3>

              <h4>boundary calls</h4>
              {selectedStep.boundaryEvents.length === 0 ? (
                <p style={{ color: "var(--text-muted)" }}>none</p>
              ) : (
                <ul className="replay-stepper__boundaries">
                  {selectedStep.boundaryEvents.map((event) => {
                    const chipColor = eventKindChipColor(event.kind);
                    return (
                      <li key={event.event_id}>
                        <span
                          className="event-kind-chip"
                          style={
                            chipColor
                              ? { background: chipColor }
                              : { border: "1px solid var(--text-muted)" }
                          }
                        />
                        {event.kind}
                        {event.fingerprint && (
                          <span className="replay-stepper__fingerprint">
                            {event.fingerprint.slice(0, 18)}&hellip;
                          </span>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}

              <h4>state diff</h4>
              <StepStateDiff step={selectedStep} />
            </div>
          )}
        </div>
      )}

      <section style={{ marginTop: "2rem" }}>
        <h2 style={{ fontSize: "0.95rem", color: "var(--text-secondary)" }}>
          Divergence report (sample)
        </h2>
        <p style={{ color: "var(--text-muted)", fontSize: "0.78rem", marginBottom: "0.75rem" }}>
          No endpoint serves a live divergence report yet — a replay session runs inside the SDK's
          own Python process (<code>trazo verify &lt;run_id&gt;</code>), not behind this API.
          Fixture data, shown here to demonstrate the view (TRZ-P6-07) — see
          src/replayFixtures/README.md.
        </p>
        <DivergenceReport report={sampleDivergenceReport} />
      </section>
    </section>
  );
}
