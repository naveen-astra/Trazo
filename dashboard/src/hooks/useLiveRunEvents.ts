import { useEffect, useRef, useState } from "react";

import { liveRunUrl, type EventOut } from "../api/runApi";

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
  const seenSeqs = useRef<Set<number>>(new Set());

  useEffect(() => {
    setEvents([]);
    setConnected(false);
    setClosed(false);
    seenSeqs.current = new Set();

    const source = new EventSource(liveRunUrl(runId));

    source.onopen = () => setConnected(true);

    source.onmessage = (message: MessageEvent<string>) => {
      const parsed = JSON.parse(message.data) as EventOut;
      if (seenSeqs.current.has(parsed.seq)) {
        return;
      }
      seenSeqs.current.add(parsed.seq);
      setEvents((prev) => [...prev, parsed].sort((a, b) => a.seq - b.seq));
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
