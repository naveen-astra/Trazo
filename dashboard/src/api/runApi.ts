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
export type StatsOut = components["schemas"]["StatsOut"];
export type StatsDailyPoint = components["schemas"]["StatsDailyPoint"];
export type StatsProjectCost = components["schemas"]["StatsProjectCost"];

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

/** Fleet-wide rollups for the Overview. Every number it shows is computed
 * server-side (ARCHITECTURE.md §2.3: the dashboard is a pure consumer and
 * computes no rollups of its own). */
export function getStats(): Promise<StatsOut> {
  return fetchJson<StatsOut>("/v1/stats");
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

// The replay-bundle endpoint returns raw NDJSON (application/x-ndjson,
// query.py's get_replay_bundle), not a JSON body FastAPI can generate an
// OpenAPI schema for -- these two types are hand-written to match that
// handler's manifest/event shape exactly (REPLAY_ENGINE.md §7).
export interface ReplayBundleManifest {
  schema: string;
  run_id: string;
  project_id: string;
  framework: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  tags: Record<string, unknown>;
  totals: Record<string, unknown>;
  event_count: number;
  blob_manifest: { sha256: string; bytes: number }[];
}

export interface ReplayBundle {
  manifest: ReplayBundleManifest;
  events: EventOut[];
}

export async function getReplayBundle(runId: string): Promise<ReplayBundle> {
  const path = `/v1/runs/${encodeURIComponent(runId)}/replay-bundle`;
  const response = await fetch(`${BASE_URL}${path}`);
  if (!response.ok) {
    throw new Error(`${path} -> HTTP ${response.status}`);
  }
  const text = await response.text();
  const lines = text.split("\n").filter((line) => line.trim().length > 0);
  const [manifestLine, ...eventLines] = lines;
  if (manifestLine === undefined) {
    throw new Error(`${path} -> empty replay bundle`);
  }
  return {
    manifest: JSON.parse(manifestLine) as ReplayBundleManifest,
    events: eventLines.map((line) => JSON.parse(line) as EventOut),
  };
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
