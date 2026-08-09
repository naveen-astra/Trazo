import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { firehoseUrl } from "../api/runApi";

// How long after the last streamed event to stop showing the "live" tick.
const IDLE_MS = 2500;
// Coalesce bursts: one run emits ~50 events in well under a second, and
// re-reading the aggregates once per event would hammer the API for no
// visible benefit.
const COALESCE_MS = 400;

/** The subset of a streamed event this hook exposes to callers that want
 * to react to *what* happened, not just *that* something happened
 * (e.g. firing a desktop notification on a critical detection). */
export interface LiveEvent {
  kind: string;
  run_id: string;
  event_id: string;
  payload: Record<string, unknown>;
}

export interface LiveRefreshState {
  connected: boolean;
  /** Briefly true right after events land — drives the "live" pulse. */
  streaming: boolean;
  lastEventAt: number | null;
  /** The most recently streamed event, best-effort parsed. `null` until
   * the first message arrives, or if `enabled` is false. */
  lastEvent: LiveEvent | null;
}

export interface UseLiveRefreshOptions {
  /** Settings → Preferences → Live updates. When false, no EventSource
   * is opened at all — views only refresh on navigation. Default true. */
  enabled?: boolean;
}

/** Subscribes to the fleet-wide (or per-project) SSE firehose and
 * invalidates the cached list/aggregate queries whenever events land.
 *
 * This is what makes the dashboard genuinely real-time rather than
 * poll-on-a-timer: the server already streams every persisted event
 * (TRZ-P2-06), so a view re-reads the moment something happens instead
 * of up to one interval later. The queries themselves stay ordinary
 * react-query reads — the stream only tells them *when* to refetch, so
 * a dropped connection degrades to "stale until the next manual action"
 * rather than breaking the page.
 */
export function useLiveRefresh(
  project?: string,
  options: UseLiveRefreshOptions = {},
): LiveRefreshState {
  const { enabled = true } = options;
  const queryClient = useQueryClient();
  const [connected, setConnected] = useState(false);
  const [lastEventAt, setLastEventAt] = useState<number | null>(null);
  const [lastEvent, setLastEvent] = useState<LiveEvent | null>(null);
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!enabled) {
      setConnected(false);
      return;
    }

    const source = new EventSource(firehoseUrl(project));

    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.onmessage = (event) => {
      setLastEventAt(Date.now());
      // Best-effort: a parse failure must not break the invalidation
      // path below, which doesn't depend on the message's content.
      try {
        setLastEvent(JSON.parse(event.data) as LiveEvent);
      } catch {
        // leave lastEvent as it was
      }
      if (pending.current) return;
      pending.current = setTimeout(() => {
        pending.current = null;
        // Every aggregate/list view, but not the per-run SSE timeline —
        // that has its own dedicated stream and needs no invalidation.
        void queryClient.invalidateQueries({ queryKey: ["stats"] });
        void queryClient.invalidateQueries({ queryKey: ["runs"] });
        void queryClient.invalidateQueries({ queryKey: ["recent-events"] });
        void queryClient.invalidateQueries({ queryKey: ["tools"] });
        void queryClient.invalidateQueries({ queryKey: ["agents"] });
        void queryClient.invalidateQueries({ queryKey: ["projects"] });
        void queryClient.invalidateQueries({ queryKey: ["models"] });
        void queryClient.invalidateQueries({ queryKey: ["detections-feed"] });
        void queryClient.invalidateQueries({ queryKey: ["policy-decisions-feed"] });
      }, COALESCE_MS);
    };

    return () => {
      source.close();
      if (pending.current) {
        clearTimeout(pending.current);
        pending.current = null;
      }
    };
  }, [project, queryClient, enabled]);

  const streaming = lastEventAt !== null && Date.now() - lastEventAt < IDLE_MS;
  return { connected, streaming, lastEventAt, lastEvent };
}
