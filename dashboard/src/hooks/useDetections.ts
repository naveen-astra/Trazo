import { useQuery } from "@tanstack/react-query";

import { listRunDetections } from "../api/runApi";

const DETECTIONS_POLL_INTERVAL_MS = 3000;

// TRZ-P5-06: polls the same way useRun does — a running run's detections
// can grow at any moment, and there's no push channel for them yet (that's
// what the live event stream already covers for everything else).
export function useDetections(runId: string, runStatus: string | undefined) {
  return useQuery({
    queryKey: ["detections", runId],
    queryFn: () => listRunDetections(runId),
    refetchInterval: runStatus === "running" ? DETECTIONS_POLL_INTERVAL_MS : false,
  });
}
