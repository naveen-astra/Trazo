import { eventKindChipColor } from "../lib/eventKind";
import { boundaryMix, type StepNode } from "../lib/runGraph";
import { IconArrowRight } from "./Icons";

interface Props {
  nodes: StepNode[];
  selectedKey: string | null;
  onSelect: (node: StepNode) => void;
}

function formatDuration(ms: number | null): string | null {
  if (ms === null) return null;
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
}

/** The run's control flow as a left-to-right chain of step nodes, each
 * carrying the boundary calls it made. Deliberately a linear chain, not
 * a free-form node graph: a step stream *is* linear (one step.started is
 * open at a time — see lib/runGraph.ts), so drawing branches would
 * invent structure the events don't record. */
export default function ExecutionGraph({ nodes, selectedKey, onSelect }: Props) {
  if (nodes.length === 0) {
    return <div className="empty-state">No steps recorded for this run.</div>;
  }

  return (
    <div className="graph">
      <div className="graph__row">
        {nodes.map((node, index) => {
          const mix = boundaryMix(node);
          const duration = formatDuration(node.durationMs);
          return (
            <div key={node.key} style={{ display: "contents" }}>
              {index > 0 && (
                <span className="graph__arrow" aria-hidden>
                  <IconArrowRight size={13} />
                </span>
              )}
              <button
                type="button"
                className={
                  node.key === selectedKey ? "graph__node graph__node--selected" : "graph__node"
                }
                onClick={() => onSelect(node)}
                aria-pressed={node.key === selectedKey}
              >
                <span className="graph__node-name" title={node.name}>
                  {node.name}
                </span>
                <span className="graph__node-sub">
                  <span>#{node.index}</span>
                  {duration && <span>· {duration}</span>}
                  {node.boundaries.length > 0 && (
                    <span>
                      · {node.boundaries.length} call
                      {node.boundaries.length === 1 ? "" : "s"}
                    </span>
                  )}
                </span>
                {mix.length > 0 && (
                  /* Composition bar: one segment per boundary kind, sized
                     by count. Colors are the same three kind chips used
                     in the timeline, so a kind reads identically in both
                     views; kinds without a validated hue fall back to
                     muted ink rather than borrowing a series color. */
                  <span className="graph__node-bar" aria-hidden>
                    {mix.map(({ kind, count }) => (
                      <span
                        key={kind}
                        className="graph__node-seg"
                        style={{
                          flexGrow: count,
                          background: eventKindChipColor(kind) ?? "var(--text-muted)",
                        }}
                      />
                    ))}
                  </span>
                )}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
