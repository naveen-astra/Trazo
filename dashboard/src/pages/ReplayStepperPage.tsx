import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { isBlobRef } from "../api/runApi";
import DivergenceReport from "../components/DivergenceReport";
import {
  IconPause,
  IconPlay,
  IconRestart,
  IconSkipBack,
  IconStepBack,
  IconStepForward,
} from "../components/Icons";
import { BlobField } from "../components/PayloadDrawer";
import { useReplayBundle } from "../hooks/useReplayBundle";
import { eventKindChipColor } from "../lib/eventKind";
import { buildStepNodes, type StepNode } from "../lib/runGraph";
import sampleDivergenceReport from "../replayFixtures/sample-divergence-report.json";

const AUTOPLAY_INTERVAL_MS = 1100;

interface StateDiffEntry {
  key: string;
  status: "added" | "removed" | "changed" | "unchanged";
  before: unknown;
  after: unknown;
}

// A flat, top-level-key diff — enough for typical agent state dicts (a
// handful of top-level fields); not a recursive/structural diff.
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

function snapshot(node: StepNode, which: "state_before" | "state_after"): unknown {
  const event = which === "state_before" ? node.started : node.finished;
  if (!event) return undefined;
  return (event.payload as Record<string, unknown>)[which];
}

function StateSide({ label, state }: { label: string; state: unknown }) {
  if (isBlobRef(state)) {
    return (
      <div>
        <div className="inspector__section-label">{label}</div>
        <BlobField field={label} sha256={state.$blob} />
      </div>
    );
  }
  return (
    <div>
      <div className="inspector__section-label">{label}</div>
      <pre className="code-block">{JSON.stringify(state, null, 2)}</pre>
    </div>
  );
}

function StepStateDiff({ node }: { node: StepNode }) {
  const before = snapshot(node, "state_before");
  const after = snapshot(node, "state_after");

  if (isBlobRef(before) || isBlobRef(after)) {
    return (
      <div className="grid-2">
        <StateSide label="before" state={before} />
        <StateSide label="after" state={after} />
      </div>
    );
  }

  const entries = diffState(before, after);
  if (entries.length === 0) {
    return <div className="empty-state">No state recorded for this step.</div>;
  }

  return (
    <div className="table-scroll">
      <table className="diff-table">
        <thead>
          <tr>
            <th>key</th>
            <th>before</th>
            <th>after</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={entry.key} className={`diff-row--${entry.status}`}>
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
    </div>
  );
}

// TRZ-P6-07: bundle-driven step list, state before/after diff, boundary
// events inline, with transport controls that walk the recorded steps.
//
// "Play" advances the *viewer* through steps already recorded in the
// bundle — it is not re-driving the agent. A live replay session runs
// inside the SDK's own Python process (`trazo replay <run_id>`), not
// behind this API; this page is a read-only viewer over what a bundle
// already holds (REPLAY_ENGINE.md §4).
export default function ReplayStepperPage() {
  const { runId } = useParams<{ runId: string }>();
  const { data: bundle, isLoading, isError, error } = useReplayBundle(runId ?? "");
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);

  const steps = useMemo(() => (bundle ? buildStepNodes(bundle.events) : []), [bundle]);
  const lastIndex = Math.max(0, steps.length - 1);
  const current = steps[Math.min(index, lastIndex)];

  useEffect(() => {
    if (!playing || steps.length === 0) return;
    const timer = setInterval(() => {
      setIndex((i) => {
        if (i >= steps.length - 1) {
          setPlaying(false);
          return i;
        }
        return i + 1;
      });
    }, AUTOPLAY_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [playing, steps.length]);

  if (!runId) {
    return (
      <div className="page">
        <p className="muted">No run id.</p>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="row" style={{ gap: 8 }}>
        <Link to={`/runs/${runId}`} className="chip">
          &larr; Back to run
        </Link>
      </div>

      <div className="page__head">
        <h1 className="page__title">Replay Studio</h1>
        <span className="page__sub mono">{runId}</span>
      </div>

      {isLoading && <p className="muted">Loading replay bundle&hellip;</p>}
      {isError && (
        <p style={{ color: "var(--status-critical)" }}>
          Failed to load replay bundle: {error instanceof Error ? error.message : String(error)}
        </p>
      )}

      {bundle && steps.length === 0 && (
        <div className="card">
          <div className="empty-state">No steps recorded for this run.</div>
        </div>
      )}

      {steps.length > 0 && current && (
        <>
          <div className="card">
            <div className="replay-controls">
              <button
                type="button"
                className="replay-btn"
                onClick={() => {
                  setPlaying(false);
                  setIndex(0);
                }}
                disabled={index === 0}
                aria-label="Jump to first step"
              >
                <IconSkipBack />
              </button>
              <button
                type="button"
                className="replay-btn"
                onClick={() => {
                  setPlaying(false);
                  setIndex((i) => Math.max(0, i - 1));
                }}
                disabled={index === 0}
                aria-label="Previous step"
              >
                <IconStepBack />
              </button>
              <button
                type="button"
                className="replay-btn replay-btn--primary"
                onClick={() => setPlaying((p) => !p)}
                disabled={index >= lastIndex && !playing}
                aria-label={playing ? "Pause" : "Play"}
              >
                {playing ? <IconPause /> : <IconPlay />}
                {playing ? "Pause" : "Play"}
              </button>
              <button
                type="button"
                className="replay-btn"
                onClick={() => {
                  setPlaying(false);
                  setIndex((i) => Math.min(lastIndex, i + 1));
                }}
                disabled={index >= lastIndex}
                aria-label="Next step"
              >
                <IconStepForward />
              </button>
              <button
                type="button"
                className="replay-btn"
                onClick={() => {
                  setPlaying(false);
                  setIndex(0);
                }}
                aria-label="Restart"
              >
                <IconRestart /> Restart
              </button>
              <span className="muted" style={{ marginLeft: "auto", fontSize: 12.5 }}>
                Step {index + 1} / {steps.length}
                {playing ? " · playing" : ""}
              </span>
            </div>

            {/* Scrubber: click anywhere to jump to that step. */}
            <div
              className="scrubber"
              role="slider"
              aria-label="Replay position"
              aria-valuemin={1}
              aria-valuemax={steps.length}
              aria-valuenow={index + 1}
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === "ArrowRight") setIndex((i) => Math.min(lastIndex, i + 1));
                if (event.key === "ArrowLeft") setIndex((i) => Math.max(0, i - 1));
              }}
              onClick={(event) => {
                const box = event.currentTarget.getBoundingClientRect();
                const ratio = (event.clientX - box.left) / box.width;
                setPlaying(false);
                setIndex(Math.min(lastIndex, Math.max(0, Math.round(ratio * lastIndex))));
              }}
            >
              <div
                className="scrubber__fill"
                style={{ width: `${lastIndex === 0 ? 100 : (index / lastIndex) * 100}%` }}
              />
              <div
                className="scrubber__thumb"
                style={{ left: `${lastIndex === 0 ? 100 : (index / lastIndex) * 100}%` }}
              />
            </div>
            <div className="scrubber__ticks">
              <span>{steps[0]?.name ?? ""}</span>
              <span>{steps[lastIndex]?.name ?? ""}</span>
            </div>
          </div>

          <div className="detail-split">
            <div className="stack">
              <div className="card">
                <div className="card__head">
                  <h2 className="card__title">
                    Step #{current.index} · {current.name}
                  </h2>
                  <span className="muted" style={{ fontSize: 12 }}>
                    {current.boundaries.length} boundary call
                    {current.boundaries.length === 1 ? "" : "s"}
                  </span>
                </div>

                {current.boundaries.length > 0 && (
                  <div className="stack" style={{ gap: 3, marginBottom: 12 }}>
                    {current.boundaries.map((event) => {
                      const color = eventKindChipColor(event.kind);
                      return (
                        <div className="timeline__event" key={event.event_id}>
                          <span
                            className="chip__dot"
                            style={
                              color
                                ? { background: color }
                                : { border: "1px solid var(--text-muted)" }
                            }
                          />
                          <span className="timeline__kind">{event.kind}</span>
                          {event.fingerprint && (
                            <span className="muted mono" style={{ fontSize: 11 }}>
                              {event.fingerprint.slice(0, 22)}…
                            </span>
                          )}
                          <span className="timeline__seq">#{event.seq}</span>
                        </div>
                      );
                    })}
                  </div>
                )}

                <div className="inspector__section-label">State diff</div>
                <StepStateDiff node={current} />
              </div>
            </div>

            <aside className="inspector">
              <div className="inspector__head">
                <span className="inspector__title">Steps</span>
                <span className="muted" style={{ fontSize: 12 }}>
                  {steps.length}
                </span>
              </div>
              <div className="step-rail">
                {steps.map((step, i) => (
                  <button
                    key={step.key}
                    type="button"
                    className={
                      i === index ? "step-rail__item step-rail__item--active" : "step-rail__item"
                    }
                    onClick={() => {
                      setPlaying(false);
                      setIndex(i);
                    }}
                  >
                    <span className="step-rail__idx">#{i}</span>
                    {step.name}
                  </button>
                ))}
              </div>
            </aside>
          </div>
        </>
      )}

      <div className="card">
        <div className="card__head">
          <h2 className="card__title">Divergence report (sample)</h2>
        </div>
        <p className="muted" style={{ fontSize: 12.5, marginTop: 0 }}>
          No endpoint serves a live divergence report yet — a replay session runs inside the
          SDK&apos;s own Python process (<code className="mono">trazo verify &lt;run_id&gt;</code>),
          not behind this API. Fixture data, shown here to demonstrate the view (TRZ-P6-07) — see
          src/replayFixtures/README.md.
        </p>
        <DivergenceReport report={sampleDivergenceReport} />
      </div>
    </div>
  );
}
