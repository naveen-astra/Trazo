import { useQuery } from "@tanstack/react-query";

import { listAgents, listProjects, listRecentEvents, listTools } from "../api/runApi";

// The four cross-run read surfaces, all refreshed by useLiveRefresh's SSE
// invalidation rather than their own timers (see that hook).

export function useRecentEvents(params: { kind?: string; limit?: number } = {}) {
  return useQuery({
    queryKey: ["recent-events", params],
    queryFn: () => listRecentEvents(params),
    staleTime: 2000,
  });
}

export function useTools() {
  return useQuery({ queryKey: ["tools"], queryFn: listTools, staleTime: 2000 });
}

export function useAgents() {
  return useQuery({ queryKey: ["agents"], queryFn: listAgents, staleTime: 2000 });
}

export function useProjects() {
  return useQuery({ queryKey: ["projects"], queryFn: listProjects, staleTime: 10000 });
}
