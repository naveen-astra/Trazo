import { useEffect, useRef, useState } from "react";

import { liveRunUrl, type EventOut } from "../api/runApi";
import { compareEvents } from "../lib/eventOrder";

export interface LiveRunEventsState {
  events: EventOut[];
  connected: boolean;
  /** True once the server closed the stream (run reached run.finished). */
  closed: boolean;
}

/** GET /v1/live/runs/{run_id} streams every persisted event for the run
 * from the start, then keeps tailing until run.finished — one mechanism
 * covers both "replay a finished run" and "watch a live run" (TRZ-P2-06's
 * design), so this hook is the single data source for the timeline;
 * no separate REST fetch + merge needed. */
export function useLiveRunEvents(runId: string): LiveRunEventsState {
  const [events, setEvents] = useState<EventOut[]>([]);
  const [connected, setConnected] = useState(false);
  const [closed, setClosed] = useState(false);
  // Keyed on event_id: a detection shares its seq with the event it
  // follows, so a seq-keyed set silently dropped every detection.
  const seenIds = useRef<Set<string>>(new Set());

  useEffect(() => {
    setEvents([]);
    setConnected(false);
    setClosed(false);
    seenIds.current = new Set();

    const source = new EventSource(liveRunUrl(runId));

    source.onopen = () => setConnected(true);

    source.onmessage = (message: MessageEvent<string>) => {
      const parsed = JSON.parse(message.data) as EventOut;
      if (seenIds.current.has(parsed.event_id)) {
        return;
      }
      seenIds.current.add(parsed.event_id);
      setEvents((prev) => [...prev, parsed].sort(compareEvents));
      if (parsed.kind === "run.finished") {
        setClosed(true);
      }
    };

    source.onerror = () => {
      setConnected(false);
    };

    return () => {
      source.close();
    };
  }, [runId]);

  return { events, connected, closed };
}
