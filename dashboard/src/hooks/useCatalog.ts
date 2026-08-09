import { useQuery } from "@tanstack/react-query";

import {
  listAgents,
  listDetectionsFeed,
  listModels,
  listPolicyDecisionsFeed,
  listProjects,
  listRecentEvents,
  listTools,
  type ListDetectionsFeedParams,
  type ListPolicyDecisionsFeedParams,
} from "../api/runApi";

// The cross-run read surfaces, all refreshed by useLiveRefresh's SSE
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

export function useModels() {
  return useQuery({ queryKey: ["models"], queryFn: listModels, staleTime: 2000 });
}

export function useProjects() {
  return useQuery({ queryKey: ["projects"], queryFn: listProjects, staleTime: 10000 });
}

/** The Incidents page's filterable feed — distinct query key from the
 * Overview's ["stats"]-backed mini-widget, so filtering here never
 * touches that cache. */
export function useDetectionsFeed(params: ListDetectionsFeedParams = {}) {
  return useQuery({
    queryKey: ["detections-feed", params],
    queryFn: () => listDetectionsFeed(params),
    staleTime: 2000,
  });
}

/** Same relationship to the Policy page as useDetectionsFeed has to
 * Incidents. */
export function usePolicyDecisionsFeed(params: ListPolicyDecisionsFeedParams = {}) {
  return useQuery({
    queryKey: ["policy-decisions-feed", params],
    queryFn: () => listPolicyDecisionsFeed(params),
    staleTime: 2000,
  });
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
