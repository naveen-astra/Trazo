import type { EventOut } from "../api/runApi";
import { isBlobRef } from "../api/runApi";
import { eventKindChipColor } from "../lib/eventKind";
import type { StepNode } from "../lib/runGraph";

interface Props {
  node: StepNode | null;
  onSelectEvent: (event: EventOut) => void;
}

function payloadField(event: EventOut | null, key: string): unknown {
  if (!event) return undefined;
  const payload = event.payload as Record<string, unknown>;
  return payload[key];
}

function renderSnapshot(value: unknown): string {
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

/** Right-hand detail pane for whichever step the execution graph has
 * selected: its own totals, the boundary calls it made, and the state
 * snapshots on either side of it. */
export default function StepInspector({ node, onSelectEvent }: Props) {
  if (!node) {
    return (
      <aside className="inspector">
        <div className="inspector__head">
          <span className="inspector__title">Step Inspector</span>
        </div>
        <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>
          Select a step in the execution graph to inspect its calls, state, and token usage.
        </p>
      </aside>
    );
  }

  const status = payloadField(node.finished, "status");
  const stateBefore = payloadField(node.started, "state_before");
  const stateAfter = payloadField(node.finished, "state_after");

  return (
    <aside className="inspector">
      <div className="inspector__head">
        <span className="inspector__title">{node.name}</span>
        <span className="muted" style={{ fontSize: 12 }}>
          step #{node.index}
        </span>
      </div>

      <div>
        <div className="inspector__section-label">Details</div>
        <div className="kv">
          <span className="kv__k">Status</span>
          <span className="kv__v">
            {typeof status === "string" ? status : node.finished ? "ok" : "running"}
          </span>
          <span className="kv__k">Duration</span>
          <span className="kv__v">{formatDuration(node.durationMs)}</span>
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
          {node.costUsd > 0 && (
            <>
              <span className="kv__k">Cost</span>
              <span className="kv__v">${node.costUsd.toFixed(4)}</span>
            </>
          )}
        </div>
      </div>

      {node.boundaries.length > 0 && (
        <div>
          <div className="inspector__section-label">Boundary calls</div>
          <div className="stack" style={{ gap: 3 }}>
            {node.boundaries.map((event) => {
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
                  <span className="timeline__seq">#{event.seq}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {node.notices.length > 0 && (
        <div>
          <div className="inspector__section-label">Governance</div>
          <div className="stack" style={{ gap: 3 }}>
            {node.notices.map((event) => (
              <button
                key={event.event_id}
                type="button"
                className="timeline__event"
                onClick={() => onSelectEvent(event)}
              >
                <span className="timeline__kind">{event.kind}</span>
                <span className="timeline__seq">#{event.seq}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div>
        <div className="inspector__section-label">State before</div>
        <pre className="code-block">{renderSnapshot(stateBefore)}</pre>
      </div>

      <div>
        <div className="inspector__section-label">State after</div>
        <pre className="code-block">{renderSnapshot(stateAfter)}</pre>
      </div>
    </aside>
  );
}
