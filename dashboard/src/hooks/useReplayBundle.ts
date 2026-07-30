import { useQuery } from "@tanstack/react-query";

import { getReplayBundle } from "../api/runApi";

// TRZ-P6-07: a replay bundle is immutable once a run is no longer
// "running" (query.py's get_replay_bundle sets a forever Cache-Control
// on exactly that condition) -- no polling, one fetch is enough.
export function useReplayBundle(runId: string) {
  return useQuery({
    queryKey: ["replay-bundle", runId],
    queryFn: () => getReplayBundle(runId),
  });
}
