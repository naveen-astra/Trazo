import { useQuery } from "@tanstack/react-query";

import { getRun } from "../api/runApi";

const RUN_POLL_INTERVAL_MS = 3000;

export function useRun(runId: string) {
  return useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId),
    // Only the rollup (status/totals) needs polling here; the event
    // stream itself is live via useLiveRunEvents (SSE).
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? RUN_POLL_INTERVAL_MS : false,
  });
}
