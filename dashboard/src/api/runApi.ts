// Typed API client (API_SPEC.md "Query"/"Live") — types come from
// types.generated.ts (`npm run gen-api-types`), never hand-written
// (CODING_STANDARDS.md §2). Unauthenticated: query/dashboard bind to
// localhost by default (ADR-009).
import type { components } from "./types.generated";

export type RunOut = components["schemas"]["RunOut"];
export type RunsPage = components["schemas"]["RunsPage"];
export type EventOut = components["schemas"]["EventOut"];
export type EventsPage = components["schemas"]["EventsPage"];
export type DetectionOut = components["schemas"]["DetectionOut"];
export type DetectionsPage = components["schemas"]["DetectionsPage"];
export type PolicyDecisionOut = components["schemas"]["PolicyDecisionOut"];
export type PolicyDecisionsPage = components["schemas"]["PolicyDecisionsPage"];

const BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8420";

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`);
  if (!response.ok) {
    throw new Error(`${path} -> HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export interface ListRunsParams {
  project?: string;
  status?: string;
  cursor?: string;
}

export function listRuns(params: ListRunsParams = {}): Promise<RunsPage> {
  const query = new URLSearchParams();
  if (params.project) query.set("project", params.project);
  if (params.status) query.set("status", params.status);
  if (params.cursor) query.set("cursor", params.cursor);
  const qs = query.toString();
  return fetchJson<RunsPage>(`/v1/runs${qs ? `?${qs}` : ""}`);
}

export function getRun(runId: string): Promise<RunOut> {
  return fetchJson<RunOut>(`/v1/runs/${encodeURIComponent(runId)}`);
}

export interface ListRunEventsParams {
  kind?: string;
  cursor?: string;
}

export function listRunEvents(
  runId: string,
  params: ListRunEventsParams = {},
): Promise<EventsPage> {
  const query = new URLSearchParams();
  if (params.kind) query.set("kind", params.kind);
  if (params.cursor) query.set("cursor", params.cursor);
  const qs = query.toString();
  return fetchJson<EventsPage>(`/v1/runs/${encodeURIComponent(runId)}/events${qs ? `?${qs}` : ""}`);
}

export function listRunDetections(runId: string): Promise<DetectionsPage> {
  return fetchJson<DetectionsPage>(`/v1/runs/${encodeURIComponent(runId)}/detections`);
}

export function listRunPolicyDecisions(runId: string): Promise<PolicyDecisionsPage> {
  return fetchJson<PolicyDecisionsPage>(`/v1/runs/${encodeURIComponent(runId)}/policy-decisions`);
}

export function blobUrl(sha256: string): string {
  return `${BASE_URL}/v1/blobs/${encodeURIComponent(sha256)}`;
}

export function liveRunUrl(runId: string): string {
  return `${BASE_URL}/v1/live/runs/${encodeURIComponent(runId)}`;
}

/** True if a payload value is an offloaded-blob reference (EVENTS.md §1). */
export function isBlobRef(value: unknown): value is { $blob: string } {
  return (
    typeof value === "object" &&
    value !== null &&
    "$blob" in value &&
    typeof (value as { $blob: unknown }).$blob === "string"
  );
}
