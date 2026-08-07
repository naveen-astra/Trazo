import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import type { EventOut } from "../api/runApi";
import DetectionBadges from "../components/DetectionBadges";
import FlowGraph from "../components/FlowGraph";
import { IconArrowRight } from "../components/Icons";
import LiveBadge from "../components/LiveBadge";
import PayloadDrawer from "../components/PayloadDrawer";
import PolicyDecisionsPanel from "../components/PolicyDecisionsPanel";
import RunTimeline from "../components/RunTimeline";
import StatusBadge from "../components/StatusBadge";
import StepInspector from "../components/StepInspector";
import TimelineStrip from "../components/TimelineStrip";
import { useDetections } from "../hooks/useDetections";
import { useLiveRunEvents } from "../hooks/useLiveRunEvents";
import { usePolicyDecisions } from "../hooks/usePolicyDecisions";
import { useRun } from "../hooks/useRun";
import { buildStepNodes } from "../lib/runGraph";

type View = "flow" | "timeline" | "logs";
const VIEWS: { id: View; label: string }[] = [
  { id: "flow", label: "Flow" },
  { id: "timeline", label: "Timeline" },
  { id: "logs", label: "Logs" },
];

function formatDuration(totals: Record<string, unknown>): string {
  const ms = totals.duration_ms;
  if (typeof ms !== "number") return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
}

// Run detail: the flow graph is the primary view — the run's control
// flow as steps with the calls each made — backed by the same live SSE
// stream that covers both a finished run's history and a running run's
// tail (useLiveRunEvents), so a run opened while in flight fills in as
// it executes.
export default function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const { data: run, isLoading, isError, error } = useRun(runId ?? "");
  const { events, connected } = useLiveRunEvents(runId ?? "");
  const { data: detectionsPage } = useDetections(runId ?? "", run?.status);
  const { data: policyDecisionsPage } = usePolicyDecisions(runId ?? "", run?.status);

  const [view, setView] = useState<View>("flow");
  const [selectedStepKey, setSelectedStepKey] = useState<string | null>(null);
  const [drawerEvent, setDrawerEvent] = useState<EventOut | null>(null);

  const nodes = useMemo(() => buildStepNodes(events), [events]);
  const selectedNode = nodes.find((node) => node.key === selectedStepKey) ?? nodes[0] ?? null;
  const diagnostics = useMemo(
    () => events.filter((event) => event.kind === "sdk.diagnostic"),
    [events],
  );

  if (!runId) {
    return (
      <div className="page">
        <p className="muted">No run id.</p>
      </div>
    );
  }

  const totals = (run?.totals ?? {}) as Record<string, unknown>;
  const stepAt = (index: number) => {
    const next = nodes[index];
    if (next) setSelectedStepKey(next.key);
  };

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
            <span className="run-meta__label">Project</span>
            <span className="run-meta__value">{run.project_id}</span>
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
              <div className="tabs" role="tablist">
                {VIEWS.map((entry) => (
                  <button
                    key={entry.id}
                    type="button"
                    role="tab"
                    aria-selected={view === entry.id}
                    className={view === entry.id ? "tab tab--active" : "tab"}
                    onClick={() => setView(entry.id)}
                  >
                    {entry.label}
                  </button>
                ))}
              </div>
              <span className="muted" style={{ fontSize: 12 }}>
                {nodes.length} step{nodes.length === 1 ? "" : "s"} · {events.length} events
                {!connected && events.length === 0 ? " · connecting…" : ""}
              </span>
            </div>

            {view === "flow" && (
              <FlowGraph
                nodes={nodes}
                selectedKey={selectedNode?.key ?? null}
                onSelectStep={(node) => setSelectedStepKey(node.key)}
                onSelectEvent={setDrawerEvent}
              />
            )}

            {view === "timeline" &&
              (events.length === 0 ? (
                <div className="empty-state">No events yet.</div>
              ) : (
                <RunTimeline events={events} />
              ))}

            {view === "logs" &&
              (diagnostics.length === 0 ? (
                <div className="empty-state">
                  No SDK diagnostics for this run — the recorder emits
                  <code className="mono"> sdk.diagnostic</code> only when it has something to report
                  (dropped events, degraded shipping).
                </div>
              ) : (
                <RunTimeline events={diagnostics} />
              ))}

            {events.length > 0 && (
              <TimelineStrip
                events={events}
                selectedEventId={drawerEvent?.event_id ?? null}
                onSelect={setDrawerEvent}
              />
            )}
          </div>
        </div>

        <StepInspector
          node={selectedNode}
          stepCount={nodes.length}
          onPrev={() => selectedNode && stepAt(selectedNode.index - 1)}
          onNext={() => selectedNode && stepAt(selectedNode.index + 1)}
          onSelectEvent={setDrawerEvent}
        />
      </div>

      {drawerEvent && <PayloadDrawer event={drawerEvent} onClose={() => setDrawerEvent(null)} />}
    </div>
  );
}
