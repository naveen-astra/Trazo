// Typed API client (API_SPEC.md "Query"/"Live") — types come from
// types.generated.ts (`npm run gen-api-types`), never hand-written
// (CODING_STANDARDS.md §2). When the control plane has sign-in enabled,
// every read is authorized by an HttpOnly session cookie that same-origin
// fetch and EventSource send on their own; this module never sees it.
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
export type StatsDeltas = components["schemas"]["StatsDeltas"];
export type ToolStat = components["schemas"]["ToolStat"];
export type ToolsPage = components["schemas"]["ToolsPage"];
export type AgentStat = components["schemas"]["AgentStat"];
export type AgentsPage = components["schemas"]["AgentsPage"];
export type ModelStat = components["schemas"]["ModelStat"];
export type ModelsPage = components["schemas"]["ModelsPage"];
export type ProjectOut = components["schemas"]["ProjectOut"];
export type ProjectsPage = components["schemas"]["ProjectsPage"];
export type DetectionsFeedPage = components["schemas"]["DetectionsFeedPage"];
export type PolicyDecisionsFeedPage = components["schemas"]["PolicyDecisionsFeedPage"];
export type ReplayReportOut = components["schemas"]["ReplayReportOut"];
export type AuthSession = components["schemas"]["SessionOut"];

const BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8420";

/** Dispatched on window whenever a read comes back 401 — the session
 * expired or was revoked mid-use — so the sign-in gate can take over
 * instead of every panel showing its own error. */
export const UNAUTHORIZED_EVENT = "trazo:unauthorized";

export class UnauthorizedError extends Error {
  constructor(path: string) {
    super(`${path} -> HTTP 401`);
    this.name = "UnauthorizedError";
  }
}

/** A problem-details error (RFC 9457) carrying the server's own message. */
export class ApiError extends Error {
  readonly status: number;
  readonly retryAfterSeconds: number | null;

  constructor(status: number, detail: string, retryAfterSeconds: number | null) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, { credentials: "same-origin" });
  if (response.status === 401) {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    throw new UnauthorizedError(path);
  }
  if (!response.ok) {
    throw new Error(`${path} -> HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

async function problemDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // Not JSON (e.g. a proxy's own error page): fall back to the status.
  }
  return `HTTP ${response.status}`;
}

export function getAuthSession(): Promise<AuthSession> {
  return fetchJson<AuthSession>("/v1/auth/session");
}

export async function signIn(password: string): Promise<void> {
  const response = await fetch(`${BASE_URL}/v1/auth/login`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (!response.ok) {
    const retryAfter = response.headers.get("Retry-After");
    throw new ApiError(
      response.status,
      await problemDetail(response),
      retryAfter ? Number(retryAfter) : null,
    );
  }
}

export async function signOut(): Promise<void> {
  await fetch(`${BASE_URL}/v1/auth/logout`, { method: "POST", credentials: "same-origin" });
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

export interface StatsParams {
  /** Restrict to runs started in the last N days; also sets the
   * baseline the deltas compare against. Omitted = whole window. */
  days?: number;
  project?: string;
}

/** Fleet-wide rollups for the Overview. Every number it shows is computed
 * server-side (ARCHITECTURE.md §2.3: the dashboard is a pure consumer and
 * computes no rollups of its own). */
export function getStats(params: StatsParams = {}): Promise<StatsOut> {
  const query = new URLSearchParams();
  if (params.days) query.set("days", String(params.days));
  if (params.project) query.set("project", params.project);
  const qs = query.toString();
  return fetchJson<StatsOut>(`/v1/stats${qs ? `?${qs}` : ""}`);
}

/** Newest events across every run; `kind` narrows it (the Logs page
 * passes "sdk.diagnostic"). */
export function listRecentEvents(
  params: { kind?: string; limit?: number } = {},
): Promise<EventsPage> {
  const query = new URLSearchParams();
  if (params.kind) query.set("kind", params.kind);
  if (params.limit) query.set("limit", String(params.limit));
  const qs = query.toString();
  return fetchJson<EventsPage>(`/v1/events/recent${qs ? `?${qs}` : ""}`);
}

export function listTools(): Promise<ToolsPage> {
  return fetchJson<ToolsPage>("/v1/tools");
}

export function listAgents(): Promise<AgentsPage> {
  return fetchJson<AgentsPage>("/v1/agents");
}

export function listModels(): Promise<ModelsPage> {
  return fetchJson<ModelsPage>("/v1/models");
}

export function listProjects(): Promise<ProjectsPage> {
  return fetchJson<ProjectsPage>("/v1/projects");
}

export interface ListDetectionsFeedParams {
  project?: string;
  detector?: string;
  severity?: string;
  limit?: number;
}

/** Cross-run, filterable detection feed for the Incidents page — distinct
 * from StatsOut.recent_detections, which stays fixed-size for the
 * Overview's glanceable summary. */
export function listDetectionsFeed(
  params: ListDetectionsFeedParams = {},
): Promise<DetectionsFeedPage> {
  const query = new URLSearchParams();
  if (params.project) query.set("project", params.project);
  if (params.detector) query.set("detector", params.detector);
  if (params.severity) query.set("severity", params.severity);
  if (params.limit) query.set("limit", String(params.limit));
  const qs = query.toString();
  return fetchJson<DetectionsFeedPage>(`/v1/detections${qs ? `?${qs}` : ""}`);
}

export interface ListPolicyDecisionsFeedParams {
  project?: string;
  decision?: string;
  policyId?: string;
  limit?: number;
}

/** Same relationship to StatsOut.recent_policy_decisions as
 * listDetectionsFeed has to recent_detections, for the Policy page. */
export function listPolicyDecisionsFeed(
  params: ListPolicyDecisionsFeedParams = {},
): Promise<PolicyDecisionsFeedPage> {
  const query = new URLSearchParams();
  if (params.project) query.set("project", params.project);
  if (params.decision) query.set("decision", params.decision);
  if (params.policyId) query.set("policy_id", params.policyId);
  if (params.limit) query.set("limit", String(params.limit));
  const qs = query.toString();
  return fetchJson<PolicyDecisionsFeedPage>(`/v1/policy-decisions${qs ? `?${qs}` : ""}`);
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

/** The fidelity report `trazo verify <run_id>` computed and submitted —
 * `null` when the run has never been verified (the endpoint's 404),
 * which is the ordinary case, not an error to surface as one. */
export async function getReplayReport(runId: string): Promise<ReplayReportOut | null> {
  const path = `/v1/runs/${encodeURIComponent(runId)}/replay-report`;
  const response = await fetch(`${BASE_URL}${path}`);
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`${path} -> HTTP ${response.status}`);
  }
  return (await response.json()) as ReplayReportOut;
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

/** Project-wide (or, with no project, fleet-wide) SSE stream. Backs the
 * dashboard's real-time refresh: every list view re-reads the moment an
 * event lands rather than on a poll tick.
 *
 * `tail=1` because the subscriber only needs to know *that* something
 * happened — it discards the payload and re-reads through the ordinary
 * query endpoints. Without it the server replays the entire event
 * history before the first live message, which costs more the longer
 * the deployment has been recording. The browser's EventSource still
 * sends `Last-Event-ID` on reconnect, and the server honours that over
 * `tail`, so a dropped connection resumes rather than skipping ahead.
 */
export function firehoseUrl(project?: string): string {
  const params = new URLSearchParams({ tail: "1" });
  if (project) params.set("project", project);
  return `${BASE_URL}/v1/live/firehose?${params.toString()}`;
}

export function liveRunUrl(runId: string): string {
  return `${BASE_URL}/v1/live/runs/${encodeURIComponent(runId)}`;
}

export interface Healthz {
  status: string;
  version: string;
}

/** Settings → Application's "control plane version" row. */
export function getHealthz(): Promise<Healthz> {
  return fetchJson<Healthz>("/healthz");
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
