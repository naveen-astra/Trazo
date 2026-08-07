import { useQuery } from "@tanstack/react-query";

import { listRuns, type ListRunsParams } from "../api/runApi";

/** GET /v1/runs. No poll interval: useLiveRefresh invalidates this key
 * off the SSE firehose, so a new or updated run shows up the moment its
 * events land rather than on the next tick. */
export function useRuns(params: ListRunsParams = {}) {
  return useQuery({
    queryKey: ["runs", params],
    queryFn: () => listRuns(params),
    staleTime: 2000,
  });
}
