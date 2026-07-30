import { useQuery } from "@tanstack/react-query";

import { listRunPolicyDecisions } from "../api/runApi";

const POLICY_DECISIONS_POLL_INTERVAL_MS = 3000;

// TRZ-P6-05: same polling shape as useDetections -- no push channel for
// policy decisions yet, so a running run's panel polls while it's active.
export function usePolicyDecisions(runId: string, runStatus: string | undefined) {
  return useQuery({
    queryKey: ["policy-decisions", runId],
    queryFn: () => listRunPolicyDecisions(runId),
    refetchInterval: runStatus === "running" ? POLICY_DECISIONS_POLL_INTERVAL_MS : false,
  });
}
