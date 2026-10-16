import { useState } from "react";

import { isBlobRef, type EventOut } from "../api/runApi";
import { eventKindChipColor } from "../lib/eventKind";
import type { StepNode } from "../lib/runGraph";
import CopyButton from "./CopyButton";
import { IconChevronLeft, IconChevronRight } from "./Icons";
import { compareEvents, formatPosition } from "../lib/eventOrder";

type Tab = "details" | "input" | "output" | "events";
const TABS: { id: Tab; label: string }[] = [
  { id: "details", label: "Details" },
  { id: "input", label: "Input" },
  { id: "output", label: "Output" },
  { id: "events", label: "Events" },
];

function payloadField(event: EventOut | null, key: string): unknown {
  if (!event) return undefined;
  return (event.payload as Record<string, unknown>)[key];
}

function render(value: unknown): string {
  if (value === undefined) return "(not recorded)";
  if (isBlobRef(value)) {
    // Offloaded past the 32KB inline limit — the row holds a content
    // hash, not the bytes (store_worker's blob offload).
    return `offloaded to blob ${value.$blob}`;
  }
  return JSON.stringify(value, null, 2);
}

function formatDuration(ms: number | null): string {
  if (ms === null) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
}

/** Which llm.call, if any, best represents this step — used for the
 * model/params rows. A step usually makes at most one. */
function primaryLlmCall(node: StepNode): EventOut | null {
  return node.boundaries.find((event) => event.kind === "llm.call") ?? null;
}

interface Props {
  node: StepNode | null;
  stepCount: number;
  onPrev: () => void;
  onNext: () => void;
  onSelectEvent: (event: EventOut) => void;
}

/** Right-hand detail pane for the selected step: its totals, the calls
 * it made, and the state on either side of it — with prev/next stepping
 * so the whole run can be walked without going back to the graph. */
export default function StepInspector({ node, stepCount, onPrev, onNext, onSelectEvent }: Props) {
  const [tab, setTab] = useState<Tab>("details");

  if (!node) {
    return (
      <aside className="inspector">
        <div className="inspector__head">
          <span className="inspector__title">Step Inspector</span>
        </div>
        <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>
          Select a step in the flow to inspect its calls, state, and token usage.
        </p>
      </aside>
    );
  }

  const status = payloadField(node.finished, "status");
  const llm = primaryLlmCall(node);
  const llmPayload = (llm?.payload ?? {}) as Record<string, unknown>;
  const params = (llmPayload.params ?? {}) as Record<string, unknown>;

  const inputValue = payloadField(node.started, "state_before");
  const outputValue = payloadField(node.finished, "state_after");

  return (
    <aside className="inspector">
      <div className="inspector__head">
        <span className="inspector__title" title={node.name}>
          {node.name}
        </span>
        <span className="stepper">
          <button
            type="button"
            className="stepper__btn"
            onClick={onPrev}
            disabled={node.index === 0}
            aria-label="Previous step"
          >
            <IconChevronLeft />
          </button>
          <span className="stepper__label">
            Step {node.index + 1} of {stepCount}
          </span>
          <button
            type="button"
            className="stepper__btn"
            onClick={onNext}
            disabled={node.index >= stepCount - 1}
            aria-label="Next step"
          >
            <IconChevronRight />
          </button>
        </span>
      </div>

      <div className="tabs" role="tablist">
        {TABS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            role="tab"
            aria-selected={tab === entry.id}
            className={tab === entry.id ? "tab tab--active" : "tab"}
            onClick={() => setTab(entry.id)}
          >
            {entry.label}
          </button>
        ))}
      </div>

      {tab === "details" && (
        <div className="kv">
          <span className="kv__k">Status</span>
          <span className="kv__v">
            {typeof status === "string" ? status : node.finished ? "ok" : "running"}
          </span>
          <span className="kv__k">Start time</span>
          <span className="kv__v">{new Date(node.started.ts).toLocaleTimeString()}</span>
          <span className="kv__k">Duration</span>
          <span className="kv__v">{formatDuration(node.durationMs)}</span>
          {typeof llmPayload.model === "string" && (
            <>
              <span className="kv__k">Model</span>
              <span className="kv__v">{llmPayload.model}</span>
            </>
          )}
          {typeof llmPayload.provider === "string" && (
            <>
              <span className="kv__k">Provider</span>
              <span className="kv__v">{llmPayload.provider}</span>
            </>
          )}
          <span className="kv__k">Boundary calls</span>
          <span className="kv__v">{node.boundaries.length}</span>
          {(node.tokensIn > 0 || node.tokensOut > 0) && (
            <>
              <span className="kv__k">Tokens</span>
              <span className="kv__v">
                {node.tokensIn + node.tokensOut} (&uarr;{node.tokensIn} &darr;
                {node.tokensOut})
              </span>
            </>
          )}
          <span className="kv__k">Cost</span>
          <span className="kv__v">${node.costUsd.toFixed(4)}</span>
          {/* Only rendered when the adapter actually captured them —
              the fixture demos record params: {} , and an invented
              temperature would be a lie about what ran. */}
          {Object.entries(params).map(([key, value]) => (
            <span style={{ display: "contents" }} key={key}>
              <span className="kv__k">{key}</span>
              <span className="kv__v">{String(value)}</span>
            </span>
          ))}
        </div>
      )}

      {tab === "input" && (
        <div>
          <div className="inspector__section-head">
            <span className="inspector__section-label">State before step</span>
            <CopyButton value={render(inputValue)} label="Copy input" />
          </div>
          <pre className="code-block">{render(inputValue)}</pre>
          {llm && (
            <>
              <div className="inspector__section-head" style={{ marginTop: 10 }}>
                <span className="inspector__section-label">LLM messages in</span>
                <CopyButton value={render(llmPayload.messages_in)} label="Copy messages" />
              </div>
              <pre className="code-block">{render(llmPayload.messages_in)}</pre>
            </>
          )}
        </div>
      )}

      {tab === "output" && (
        <div>
          <div className="inspector__section-head">
            <span className="inspector__section-label">State after step</span>
            <CopyButton value={render(outputValue)} label="Copy output" />
          </div>
          <pre className="code-block">{render(outputValue)}</pre>
          {llm && (
            <>
              <div className="inspector__section-head" style={{ marginTop: 10 }}>
                <span className="inspector__section-label">LLM response</span>
                <CopyButton value={render(llmPayload.response)} label="Copy response" />
              </div>
              <pre className="code-block">{render(llmPayload.response)}</pre>
            </>
          )}
        </div>
      )}

      {tab === "events" && (
        <div className="stack" style={{ gap: 3 }}>
          {[...node.boundaries, ...node.notices].length === 0 ? (
            <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>
              No boundary calls in this step.
            </p>
          ) : (
            [...node.boundaries, ...node.notices].sort(compareEvents).map((event) => {
              const color = eventKindChipColor(event.kind);
              return (
                <button
                  key={event.event_id}
                  type="button"
                  className="timeline__event"
                  onClick={() => onSelectEvent(event)}
                >
                  <span
                    className="chip__dot"
                    style={
                      color ? { background: color } : { border: "1px solid var(--text-muted)" }
                    }
                  />
                  <span className="timeline__kind">{event.kind}</span>
                  <span className="timeline__seq">#{formatPosition(event)}</span>
                </button>
              );
            })
          )}
        </div>
      )}
    </aside>
  );
}
