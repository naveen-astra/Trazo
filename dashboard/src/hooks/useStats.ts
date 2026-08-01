import { useQuery } from "@tanstack/react-query";

import { getStats } from "../api/runApi";

const STATS_POLL_INTERVAL_MS = 5000;

/** Polls GET /v1/stats — the Overview's whole data source (counters,
 * daily series, cost split, incident feed) in one round trip. Slower
 * cadence than the run list: these are fleet-wide rollups, not a live
 * timeline, so a 5s refresh reads as current without re-aggregating on
 * the server every few hundred ms. */
export function useStats() {
  return useQuery({
    queryKey: ["stats"],
    queryFn: getStats,
    refetchInterval: STATS_POLL_INTERVAL_MS,
  });
}
