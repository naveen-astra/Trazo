import { useQuery } from "@tanstack/react-query";

import { getStats, type StatsParams } from "../api/runApi";

/** GET /v1/stats — the Overview's whole data source (counters, deltas,
 * daily series, cost split, incident + policy feeds) in one round trip.
 *
 * No refetchInterval: useLiveRefresh invalidates this key the moment the
 * SSE firehose reports new events, so the page is driven by what
 * actually happened rather than a timer. `staleTime` keeps a filter
 * toggle from re-fetching a window already in cache.
 */
export function useStats(params: StatsParams = {}) {
  return useQuery({
    queryKey: ["stats", params],
    queryFn: () => getStats(params),
    staleTime: 2000,
  });
}
