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

/** Resolve a `project_id` to the name the SDK was configured with.
 *
 * Runs, stats and events all carry the hashed `project_id`; only
 * /v1/projects knows the name behind it. Reads from the same cached
 * query the project filter uses, and falls back to the id so a project
 * that has no row yet still renders something truthful rather than
 * blank.
 */
export function useProjectName(): (projectId: string) => string {
  const { data } = useProjects();
  return (projectId: string) =>
    data?.projects.find((p) => p.project_id === projectId)?.name ?? projectId;
}
