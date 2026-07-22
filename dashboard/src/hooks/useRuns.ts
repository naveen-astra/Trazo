import { useQuery } from "@tanstack/react-query";

import { listRuns, type ListRunsParams } from "../api/runApi";

const LIST_POLL_INTERVAL_MS = 3000;

/** Polls GET /v1/runs so new/updated runs appear without a manual refresh
 * — simpler than a firehose SSE subscription for a list view, and the
 * SSE budget is spent on the run-detail timeline instead (useLiveRunEvents). */
export function useRuns(params: ListRunsParams = {}) {
  return useQuery({
    queryKey: ["runs", params],
    queryFn: () => listRuns(params),
    refetchInterval: LIST_POLL_INTERVAL_MS,
  });
}
