import { useState } from "react";

import type { EventOut } from "../api/runApi";
import { eventKindChipColor } from "../lib/eventKind";
import PayloadDrawer from "./PayloadDrawer";
import { formatPosition } from "../lib/eventOrder";

interface RunTimelineProps {
  events: EventOut[];
}

interface StepGroup {
  stepId: string | null;
  stepName: string | null;
  events: EventOut[];
}

// step_id is attached to every event emitted while a step_scope is active
// — including that step's own step.started/step.finished (trazo.core.
// context, SDK.md §2) — so grouping by step_id alone is enough to nest a
// step's boundary calls under it; events with no step_id (run.started,
// run.finished) each get their own singleton group.
function groupByStep(events: EventOut[]): StepGroup[] {
  const order: string[] = [];
  const byKey = new Map<string, StepGroup>();

  events.forEach((event, index) => {
    const key = event.step_id ?? `__none_${index}`;
    let group = byKey.get(key);
    if (!group) {
      group = { stepId: event.step_id, stepName: null, events: [] };
      byKey.set(key, group);
      order.push(key);
    }
    group.events.push(event);
    if (event.kind === "step.started") {
      const name = (event.payload as { name?: unknown }).name;
      group.stepName = typeof name === "string" ? name : null;
    }
  });

  return order.flatMap((key) => {
    const group = byKey.get(key);
    return group ? [group] : [];
  });
}

/** Kind-colored, step-grouped event timeline with a payload drawer
 * (TRZ-P2-07). Pure rendering of whatever `events` already is — no
 * client-side business logic, per the task's DoD. */
export default function RunTimeline({ events }: RunTimelineProps) {
  const [selected, setSelected] = useState<EventOut | null>(null);
  const groups = groupByStep(events);

  return (
    <div className="timeline">
      {groups.map((group, index) => (
        <div
          className={group.stepId !== null ? "timeline__step" : undefined}
          key={group.stepId ?? `ungrouped-${index}`}
        >
          {group.stepId !== null && (
            <div className="timeline__step-name">step: {group.stepName ?? group.stepId}</div>
          )}
          {group.events.map((event) => {
            const chipColor = eventKindChipColor(event.kind);
            return (
              <button
                key={event.event_id}
                id={`evt-${event.event_id}`}
                type="button"
                className={
                  selected?.event_id === event.event_id
                    ? "timeline__event timeline__event--selected"
                    : "timeline__event"
                }
                onClick={() => setSelected(event)}
              >
                <span
                  className="chip__dot"
                  style={
                    chipColor
                      ? { background: chipColor }
                      : { border: "1px solid var(--text-muted)" }
                  }
                />
                <span className="timeline__kind">{event.kind}</span>
                <span className="timeline__seq">#{formatPosition(event)}</span>
              </button>
            );
          })}
        </div>
      ))}
      {selected && <PayloadDrawer event={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
