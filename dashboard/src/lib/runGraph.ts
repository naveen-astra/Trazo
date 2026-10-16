import type { EventOut } from "../api/runApi";
import { compareEvents } from "./eventOrder";

// Turns a flat event stream into the step nodes the execution graph and
// the step inspector both render.
//
// Walks events in seq order and attributes each boundary call to
// whichever step.started is currently open, rather than joining on
// step_id. Verified against real recorded bundles: the LangGraph
// adapter's own llm.call/tool.call/memory.* events carry step_id: null
// in practice (only step.started/step.finished carry a real one), so a
// step_id join silently leaves every node's call list empty. Positional
// attribution also matches how a reader scans a timeline anyway.

export const BOUNDARY_KINDS = [
  "llm.call",
  "tool.call",
  "memory.read",
  "memory.write",
  "human.checkpoint",
] as const;

const BOUNDARY_SET = new Set<string>(BOUNDARY_KINDS);

export interface StepNode {
  key: string;
  index: number;
  name: string;
  started: EventOut;
  finished: EventOut | null;
  boundaries: EventOut[];
  /** Governance/diagnostic events that landed inside this step. */
  notices: EventOut[];
  durationMs: number | null;
  costUsd: number;
  tokensIn: number;
  tokensOut: number;
}

function numberField(payload: unknown, key: string): number {
  if (payload && typeof payload === "object") {
    const value = (payload as Record<string, unknown>)[key];
    if (typeof value === "number") return value;
  }
  return 0;
}

export function buildStepNodes(events: EventOut[]): StepNode[] {
  const ordered = [...events].sort(compareEvents);
  const nodes: StepNode[] = [];
  let current: StepNode | null = null;

  for (const event of ordered) {
    if (event.kind === "step.started") {
      const name = (event.payload as { name?: unknown }).name;
      current = {
        key: event.event_id,
        index: nodes.length,
        name: typeof name === "string" && name ? name : `step ${nodes.length}`,
        started: event,
        finished: null,
        boundaries: [],
        notices: [],
        durationMs: null,
        costUsd: 0,
        tokensIn: 0,
        tokensOut: 0,
      };
      nodes.push(current);
      continue;
    }

    if (!current) continue;

    if (event.kind === "step.finished") {
      current.finished = event;
      const duration = numberField(event.payload, "duration_ms");
      current.durationMs = duration || null;
      current = null;
      continue;
    }

    if (BOUNDARY_SET.has(event.kind)) {
      current.boundaries.push(event);
      if (event.kind === "llm.call") {
        current.costUsd += numberField(event.payload, "cost_usd");
        current.tokensIn += numberField(event.payload, "tokens_in");
        current.tokensOut += numberField(event.payload, "tokens_out");
      }
    } else if (
      event.kind === "policy.decision" ||
      event.kind === "detection.raised" ||
      event.kind === "sdk.diagnostic"
    ) {
      current.notices.push(event);
    }
  }

  return nodes;
}

/** Per-kind counts for a node's mini composition bar. */
export function boundaryMix(node: StepNode): { kind: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const event of node.boundaries) {
    counts.set(event.kind, (counts.get(event.kind) ?? 0) + 1);
  }
  return [...counts.entries()].map(([kind, count]) => ({ kind, count }));
}
