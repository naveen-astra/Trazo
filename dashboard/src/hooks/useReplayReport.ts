import { useQuery } from "@tanstack/react-query";

import { getReplayReport } from "../api/runApi";

/** The real fidelity report `trazo verify <run_id>` computed and
 * submitted (POST /v1/runs/{run_id}/replay-report) — `data` is `null`
 * when the run has never been verified, not an error state. No polling:
 * a report only changes when someone runs `trazo verify` again, which
 * this page can't observe happening. */
export function useReplayReport(runId: string) {
  return useQuery({
    queryKey: ["replay-report", runId],
    queryFn: () => getReplayReport(runId),
  });
}
