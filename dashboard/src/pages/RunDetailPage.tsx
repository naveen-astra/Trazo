import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import type { EventOut } from "../api/runApi";
import DetectionBadges from "../components/DetectionBadges";
import ExecutionGraph from "../components/ExecutionGraph";
import { IconArrowRight } from "../components/Icons";
import LiveBadge from "../components/LiveBadge";
import PayloadDrawer from "../components/PayloadDrawer";
import PolicyDecisionsPanel from "../components/PolicyDecisionsPanel";
import RunTimeline from "../components/RunTimeline";
import StatusBadge from "../components/StatusBadge";
import StepInspector from "../components/StepInspector";
import { useDetections } from "../hooks/useDetections";
import { useLiveRunEvents } from "../hooks/useLiveRunEvents";
import { usePolicyDecisions } from "../hooks/usePolicyDecisions";
import { useRun } from "../hooks/useRun";
import { buildStepNodes } from "../lib/runGraph";

function formatDuration(totals: Record<string, unknown>): string {
  const ms = totals.duration_ms;
  if (typeof ms !== "number") return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
}

// Run detail (TRZ-P2-07 + TRZ-P6): the execution graph is the primary
// view — a run's control flow as steps, each selectable into the right-
// hand inspector — with the full kind-colored timeline underneath for
// the event-by-event read. The event stream comes from useLiveRunEvents
// (GET /v1/live/runs/{id}), which covers both a finished run's history
// and a running run's live tail in one mechanism.
export default function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const { data: run, isLoading, isError, error } = useRun(runId ?? "");
  const { events, connected } = useLiveRunEvents(runId ?? "");
  const { data: detectionsPage } = useDetections(runId ?? "", run?.status);
  const { data: policyDecisionsPage } = usePolicyDecisions(runId ?? "", run?.status);

  const [selectedStepKey, setSelectedStepKey] = useState<string | null>(null);
  const [drawerEvent, setDrawerEvent] = useState<EventOut | null>(null);

  const nodes = useMemo(() => buildStepNodes(events), [events]);
  const selectedNode = nodes.find((node) => node.key === selectedStepKey) ?? nodes[0] ?? null;

  if (!runId) {
    return (
      <div className="page">
        <p className="muted">No run id.</p>
      </div>
    );
  }

  const totals = (run?.totals ?? {}) as Record<string, unknown>;

  return (
    <div className="page">
      <div className="row" style={{ gap: 8 }}>
        <Link to="/runs" className="chip">
          &larr; All runs
        </Link>
      </div>

      <div className="run-head">
        <span className="run-head__id">{runId}</span>
        {run && <StatusBadge status={run.status} />}
        {run?.status === "running" && <LiveBadge />}
        <span style={{ marginLeft: "auto" }} />
        {run && run.status !== "running" && (
          <Link to={`/runs/${runId}/replay`} className="chip">
            Replay Studio <IconArrowRight />
          </Link>
        )}
      </div>

      {isLoading && <p className="muted">Loading run&hellip;</p>}
      {isError && (
        <p style={{ color: "var(--status-critical)" }}>
          Failed to load run: {error instanceof Error ? error.message : String(error)}
        </p>
      )}

      {run && (
        <div className="run-meta">
          <div className="run-meta__item">
            <span className="run-meta__label">Framework</span>
            <span className="run-meta__value">{run.framework}</span>
          </div>
          <div className="run-meta__item">
            <span className="run-meta__label">Duration</span>
            <span className="run-meta__value">{formatDuration(totals)}</span>
          </div>
          <div className="run-meta__item">
            <span className="run-meta__label">Events</span>
            <span className="run-meta__value">
              {typeof totals.events === "number" ? totals.events : "—"}
            </span>
          </div>
          <div className="run-meta__item">
            <span className="run-meta__label">LLM calls</span>
            <span className="run-meta__value">
              {typeof totals.llm_calls === "number" ? totals.llm_calls : "—"}
            </span>
          </div>
          <div className="run-meta__item">
            <span className="run-meta__label">Tool calls</span>
            <span className="run-meta__value">
              {typeof totals.tool_calls === "number" ? totals.tool_calls : "—"}
            </span>
          </div>
          <div className="run-meta__item">
            <span className="run-meta__label">Cost</span>
            <span className="run-meta__value">
              {typeof totals.cost_usd === "number" ? `$${totals.cost_usd.toFixed(4)}` : "—"}
            </span>
          </div>
          <div className="run-meta__item">
            <span className="run-meta__label">Started</span>
            <span className="run-meta__value">{new Date(run.started_at).toLocaleString()}</span>
          </div>
        </div>
      )}

      <DetectionBadges detections={detectionsPage?.detections ?? []} />
      <PolicyDecisionsPanel decisions={policyDecisionsPage?.decisions ?? []} />

      <div className="detail-split">
        <div className="stack">
          <div className="card">
            <div className="card__head">
              <h2 className="card__title">Execution graph</h2>
              <span className="muted" style={{ fontSize: 12 }}>
                {nodes.length} step{nodes.length === 1 ? "" : "s"}
              </span>
            </div>
            <ExecutionGraph
              nodes={nodes}
              selectedKey={selectedNode?.key ?? null}
              onSelect={(node) => setSelectedStepKey(node.key)}
            />
          </div>

          <div className="card">
            <div className="card__head">
              <h2 className="card__title">Timeline</h2>
              {!connected && events.length === 0 && (
                <span className="muted" style={{ fontSize: 12 }}>
                  connecting&hellip;
                </span>
              )}
            </div>
            {events.length === 0 ? (
              <div className="empty-state">No events yet.</div>
            ) : (
              <RunTimeline events={events} />
            )}
          </div>
        </div>

        <StepInspector node={selectedNode} onSelectEvent={setDrawerEvent} />
      </div>

      {drawerEvent && <PayloadDrawer event={drawerEvent} onClose={() => setDrawerEvent(null)} />}
    </div>
  );
}
