// Event-kind presentation (TRZ-P2-07). Only three kinds get a categorical
// color chip — the boundary calls that carry the actual "what did the
// agent do" content (llm.call/tool.call/memory.*). That's a deliberate
// restriction, not an oversight: it's the largest subset of the
// palette's 8 categorical slots that validates all-pairs CVD/normal-
// vision separation in both light and dark (see dataviz skill,
// palette.md — slots 4+ start colliding, e.g. yellow vs orange). Every
// other kind (lifecycle, coordination, governance, diagnostic) renders
// as neutral ink instead of forcing more hues into a failing set — sorted
// with everything else by chronology, not visually competing for
// attention with the calls that actually matter on a first scan.
export type EventKind =
  | "run.started"
  | "run.finished"
  | "step.started"
  | "step.finished"
  | "llm.call"
  | "tool.call"
  | "memory.read"
  | "memory.write"
  | "agent.message"
  | "plan.updated"
  | "human.checkpoint"
  | "policy.decision"
  | "detection.raised"
  | "sdk.diagnostic";

const CHIP_COLOR_VAR: Partial<Record<EventKind, string>> = {
  "llm.call": "var(--kind-llm)",
  "tool.call": "var(--kind-tool)",
  "memory.read": "var(--kind-memory)",
  "memory.write": "var(--kind-memory)",
};

/** CSS color (custom-property reference) for the kind's chip, or null for
 * kinds that render as neutral ink with no chip. */
export function eventKindChipColor(kind: string): string | null {
  return CHIP_COLOR_VAR[kind as EventKind] ?? null;
}
