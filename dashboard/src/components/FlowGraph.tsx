import { useState } from "react";

import type { EventOut } from "../api/runApi";
import { eventKindChipColor } from "../lib/eventKind";
import type { StepNode } from "../lib/runGraph";
import { IconBrain, IconDatabase, IconWrench, IconZoomIn, IconZoomOut } from "./Icons";

// The run's control flow as a two-level graph: step nodes along the
// spine, each with the boundary calls it actually made branching off it.
//
// Deliberately a spine-with-branches rather than a free-form node graph.
// A step stream is linear — exactly one step.started is open at a time
// (lib/runGraph.ts) — so drawing arbitrary branches between steps would
// invent structure the events never recorded. What IS real is the
// fan-out from a step to its own calls, and that's what's drawn.

const ZOOM_STEPS = [0.75, 0.9, 1, 1.15, 1.35];
const DEFAULT_ZOOM_INDEX = 2;

function callIcon(kind: string) {
  if (kind === "llm.call") return <IconBrain size={13} />;
  if (kind === "tool.call") return <IconWrench size={13} />;
  if (kind.startsWith("memory.")) return <IconDatabase size={13} />;
  return null;
}

function callLabel(event: EventOut): string {
  const payload = event.payload as Record<string, unknown>;
  if (event.kind === "tool.call" && typeof payload.tool_name === "string") {
    return payload.tool_name;
  }
  if (event.kind === "llm.call" && typeof payload.model === "string") {
    return payload.model;
  }
  if (event.kind.startsWith("memory.") && typeof payload.store === "string") {
    return `${event.kind.split(".")[1]} · ${payload.store}`;
  }
  return event.kind;
}

function callSubtitle(event: EventOut): string | null {
  const payload = event.payload as Record<string, unknown>;
  const latency = payload.latency_ms;
  if (typeof latency !== "number") return null;
  return latency >= 1000 ? `${(latency / 1000).toFixed(2)}s` : `${latency.toFixed(1)}ms`;
}

function isFailedCall(event: EventOut): boolean {
  const status = (event.payload as Record<string, unknown>).status;
  return typeof status === "string" && status !== "ok";
}

interface Props {
  nodes: StepNode[];
  selectedKey: string | null;
  onSelectStep: (node: StepNode) => void;
  onSelectEvent: (event: EventOut) => void;
}

export default function FlowGraph({ nodes, selectedKey, onSelectStep, onSelectEvent }: Props) {
  const [zoomIndex, setZoomIndex] = useState(DEFAULT_ZOOM_INDEX);
  const zoom = ZOOM_STEPS[zoomIndex] ?? 1;

  if (nodes.length === 0) {
    return <div className="empty-state">No steps recorded for this run.</div>;
  }

  return (
    <div>
      <div className="flow__toolbar">
        <button
          type="button"
          className="replay-btn"
          onClick={() => setZoomIndex(DEFAULT_ZOOM_INDEX)}
          title="Reset zoom"
        >
          Auto fit
        </button>
        <button
          type="button"
          className="replay-btn"
          onClick={() => setZoomIndex((i) => Math.max(0, i - 1))}
          disabled={zoomIndex === 0}
          aria-label="Zoom out"
        >
          <IconZoomOut />
        </button>
        <button
          type="button"
          className="replay-btn"
          onClick={() => setZoomIndex((i) => Math.min(ZOOM_STEPS.length - 1, i + 1))}
          disabled={zoomIndex === ZOOM_STEPS.length - 1}
          aria-label="Zoom in"
        >
          <IconZoomIn />
        </button>
        <span className="muted" style={{ fontSize: 12, marginLeft: "auto" }}>
          {Math.round(zoom * 100)}%
        </span>
      </div>

      <div className="flow">
        <div
          className="flow__canvas"
          style={{ transform: `scale(${zoom})`, transformOrigin: "top left" }}
        >
          {nodes.map((node, index) => {
            const selected = node.key === selectedKey;
            return (
              <div className="flow__column" key={node.key}>
                {index > 0 && <span className="flow__spine-edge" aria-hidden />}

                <button
                  type="button"
                  className={selected ? "flow__step flow__step--selected" : "flow__step"}
                  onClick={() => onSelectStep(node)}
                  aria-pressed={selected}
                >
                  <span className="flow__step-index">#{node.index}</span>
                  <span className="flow__step-name" title={node.name}>
                    {node.name}
                  </span>
                  <span className="flow__step-meta">
                    {node.durationMs !== null
                      ? node.durationMs >= 1000
                        ? `${(node.durationMs / 1000).toFixed(2)}s`
                        : `${Math.round(node.durationMs)}ms`
                      : "—"}
                    {node.costUsd > 0 && ` · $${node.costUsd.toFixed(4)}`}
                  </span>
                </button>

                {node.boundaries.length > 0 && (
                  <div className="flow__calls">
                    {node.boundaries.map((event) => {
                      const color = eventKindChipColor(event.kind);
                      const failed = isFailedCall(event);
                      const subtitle = callSubtitle(event);
                      return (
                        <button
                          key={event.event_id}
                          type="button"
                          className="flow__call"
                          style={{
                            borderLeftColor: failed
                              ? "var(--status-critical)"
                              : (color ?? "var(--text-muted)"),
                          }}
                          onClick={() => onSelectEvent(event)}
                          title={`${event.kind} · seq ${event.seq}`}
                        >
                          <span
                            className="flow__call-icon"
                            style={{ color: color ?? "var(--text-muted)" }}
                          >
                            {callIcon(event.kind)}
                          </span>
                          <span className="flow__call-body">
                            <span className="flow__call-name">{callLabel(event)}</span>
                            {subtitle && <span className="flow__call-sub">{subtitle}</span>}
                          </span>
                          {failed && (
                            <span
                              className="flow__call-flag"
                              style={{ color: "var(--status-critical)" }}
                              title="Call reported a non-ok status"
                            >
                              !
                            </span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                )}

                {node.notices.length > 0 && (
                  <div className="flow__calls">
                    {node.notices.map((event) => (
                      <button
                        key={event.event_id}
                        type="button"
                        className="flow__call"
                        style={{ borderLeftColor: "var(--status-warning)" }}
                        onClick={() => onSelectEvent(event)}
                        title={`${event.kind} · seq ${event.seq}`}
                      >
                        <span className="flow__call-body">
                          <span className="flow__call-name">{event.kind}</span>
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
