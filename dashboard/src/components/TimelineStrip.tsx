import type { EventOut } from "../api/runApi";
import { eventKindChipColor } from "../lib/eventKind";
import { formatPosition } from "../lib/eventOrder";

// The whole run compressed to one bar: a segment per event, kind-colored,
// in seq order. Segments are equal-width rather than duration-scaled on
// purpose — most boundary calls in a fixture run finish in well under a
// millisecond, so a true time scale collapses them all into invisible
// slivers and reads as one solid block. Equal widths keep it legible as
// what it is: a map of *what happened in what order*, clickable to jump.

interface Props {
  events: EventOut[];
  selectedEventId: string | null;
  onSelect: (event: EventOut) => void;
}

export default function TimelineStrip({ events, selectedEventId, onSelect }: Props) {
  if (events.length === 0) return null;

  return (
    <div className="strip" role="list" aria-label="Run event map">
      {events.map((event) => {
        const color = eventKindChipColor(event.kind);
        return (
          <button
            key={event.event_id}
            type="button"
            role="listitem"
            className={
              event.event_id === selectedEventId ? "strip__seg strip__seg--on" : "strip__seg"
            }
            style={{ background: color ?? "var(--surface-3)" }}
            onClick={() => onSelect(event)}
            title={`#${formatPosition(event)} ${event.kind}`}
            aria-label={`Event ${formatPosition(event)}, ${event.kind}`}
          />
        );
      })}
    </div>
  );
}
