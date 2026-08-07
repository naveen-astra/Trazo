"""Query API: GET /v1/runs, /v1/runs/{run_id}, /v1/runs/{run_id}/events,
/v1/runs/{run_id}/replay-bundle, /v1/blobs/{sha256}.

Unauthenticated by design — "query/dashboard bind to localhost by
default" (ADR-009); only ingest and policy endpoints require the bearer
key (API_SPEC.md). Pagination is keyset-based (api/cursors.py): stable
under concurrent inserts, unlike OFFSET.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from trazo_server.api.cursors import InvalidCursorError, decode_cursor, encode_cursor
from trazo_server.api.deps import get_blob_store, get_trace_store
from trazo_server.api.problem_details import ProblemDetailsError
from trazo_server.errors import BlobNotFoundError
from trazo_server.store.blob_store import BlobStore
from trazo_server.store.rows import DetectionRow, EventRow, PolicyDecisionRow, RunRow
from trazo_server.store.trace_store import TraceStore

router = APIRouter(prefix="/v1")

_MAX_LIMIT = 1000
_DEFAULT_LIMIT = 50


class RunOut(BaseModel):
    run_id: str
    project_id: str
    framework: str
    status: str
    started_at: str
    finished_at: str | None
    tags: dict[str, Any]
    totals: dict[str, Any]


class RunsPage(BaseModel):
    runs: list[RunOut]
    next_cursor: str | None


class EventOut(BaseModel):
    run_id: str
    seq: int
    event_id: str
    kind: str
    ts: str
    step_id: str | None
    agent_id: str | None
    fingerprint: str | None
    payload: dict[str, Any]
    blobs: list[dict[str, Any]]


class EventsPage(BaseModel):
    events: list[EventOut]
    next_cursor: str | None


class DetectionOut(BaseModel):
    detection_id: str
    run_id: str
    detector: str
    severity: str
    raised_at: str
    evidence: list[dict[str, Any]]
    details: dict[str, Any]


class DetectionsPage(BaseModel):
    detections: list[DetectionOut]


class PolicyDecisionOut(BaseModel):
    decision_id: str
    run_id: str
    policy_id: str
    action_kind: str
    action_fp: str
    decision: str
    mode: str
    reasons: list[str]
    decided_at: str
    eval_ms: float


class PolicyDecisionsPage(BaseModel):
    decisions: list[PolicyDecisionOut]


class StatsDailyPoint(BaseModel):
    date: str  # YYYY-MM-DD, UTC
    runs: int
    failed_runs: int
    cost_usd: float


class StatsProjectCost(BaseModel):
    project_id: str
    runs: int
    cost_usd: float


class StatsDeltas(BaseModel):
    """Percent change of this window against the immediately preceding
    window of the same length. ``None`` where the previous window had
    nothing to compare against — the UI shows "no prior data" rather
    than a meaningless +100%."""

    runs_pct: float | None
    failed_runs_pct: float | None
    cost_pct: float | None


class StatsOut(BaseModel):
    total_runs: int
    failed_runs: int
    active_runs: int
    total_cost_usd: float
    policy_denials: int
    total_detections: int
    window_runs: int
    range_days: int | None
    deltas: StatsDeltas
    daily: list[StatsDailyPoint]
    cost_by_project: list[StatsProjectCost]
    recent_detections: list[DetectionOut]
    recent_policy_decisions: list[PolicyDecisionOut]


class ToolStat(BaseModel):
    tool_name: str
    calls: int
    errors: int
    avg_latency_ms: float
    side_effect_class: str
    last_used: str


class ToolsPage(BaseModel):
    tools: list[ToolStat]
    window_events: int


class AgentStat(BaseModel):
    agent_id: str
    events: int
    runs: int
    last_seen: str


class AgentsPage(BaseModel):
    agents: list[AgentStat]
    window_events: int
    unattributed_events: int


class ProjectOut(BaseModel):
    project_id: str
    runs: int


class ProjectsPage(BaseModel):
    projects: list[ProjectOut]


def _clamp_limit(limit: int) -> int:
    if not (1 <= limit <= _MAX_LIMIT):
        raise ProblemDetailsError(
            status=400,
            title="Invalid Limit",
            detail=f"limit must be between 1 and {_MAX_LIMIT}, got {limit}",
        )
    return limit


def _run_out(run: RunRow) -> RunOut:
    return RunOut(
        run_id=run.run_id,
        project_id=run.project_id,
        framework=run.framework,
        status=run.status,
        started_at=run.started_at.isoformat(),
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
        tags=run.tags,
        totals=run.totals,
    )


def _detection_out(detection: DetectionRow) -> DetectionOut:
    return DetectionOut(
        detection_id=detection.detection_id,
        run_id=detection.run_id,
        detector=detection.detector,
        severity=detection.severity,
        raised_at=detection.raised_at.isoformat(),
        evidence=detection.evidence,
        details=detection.details,
    )


def _policy_decision_out(decision: PolicyDecisionRow) -> PolicyDecisionOut:
    return PolicyDecisionOut(
        decision_id=decision.decision_id,
        run_id=decision.run_id,
        policy_id=decision.policy_id,
        action_kind=decision.action_kind,
        action_fp=decision.action_fp,
        decision=decision.decision,
        mode=decision.mode,
        reasons=decision.reasons,
        decided_at=decision.decided_at.isoformat(),
        eval_ms=decision.eval_ms,
    )


def _event_out(event: EventRow) -> EventOut:
    return EventOut(
        run_id=event.run_id,
        seq=event.seq,
        event_id=event.event_id,
        kind=event.kind,
        ts=event.ts.isoformat(),
        step_id=event.step_id,
        agent_id=event.agent_id,
        fingerprint=event.fingerprint,
        payload=event.payload,
        blobs=event.blobs,
    )


def _decode_runs_cursor(cursor: str) -> tuple[datetime, str]:
    decoded = decode_cursor(cursor)
    try:
        return datetime.fromisoformat(decoded["started_at"]), str(decoded["run_id"])
    except (KeyError, ValueError, TypeError) as exc:
        raise InvalidCursorError(f"invalid cursor: {cursor!r}") from exc


def _decode_events_cursor(cursor: str) -> int:
    decoded = decode_cursor(cursor)
    try:
        return int(decoded["seq"])
    except (KeyError, ValueError, TypeError) as exc:
        raise InvalidCursorError(f"invalid cursor: {cursor!r}") from exc


@router.get("/runs", response_model=RunsPage)
async def list_runs(
    store: Annotated[TraceStore, Depends(get_trace_store)],
    project: str | None = None,
    status: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    cursor: str | None = None,
) -> RunsPage:
    limit = _clamp_limit(limit)
    before: tuple[datetime, str] | None = None
    if cursor is not None:
        try:
            before = _decode_runs_cursor(cursor)
        except InvalidCursorError as exc:
            raise ProblemDetailsError(
                status=400, title="Invalid Cursor", detail=str(exc)
            ) from exc

    fetched = await store.list_runs(
        project_id=project, status=status, limit=limit + 1, before=before
    )
    page, has_more = fetched[:limit], len(fetched) > limit
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_cursor(
            {"started_at": last.started_at.isoformat(), "run_id": last.run_id}
        )

    return RunsPage(runs=[_run_out(r) for r in page], next_cursor=next_cursor)


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(
    run_id: str, store: Annotated[TraceStore, Depends(get_trace_store)]
) -> RunOut:
    run = await store.get_run(run_id)
    if run is None:
        raise ProblemDetailsError(
            status=404, title="Not Found", detail=f"no run {run_id}"
        )
    return _run_out(run)


@router.get("/runs/{run_id}/events", response_model=EventsPage)
async def list_events(
    run_id: str,
    store: Annotated[TraceStore, Depends(get_trace_store)],
    kind: str | None = None,
    after_seq: int | None = None,
    limit: int = _DEFAULT_LIMIT,
    cursor: str | None = None,
) -> EventsPage:
    limit = _clamp_limit(limit)
    cursor_seq: int | None = None
    if cursor is not None:
        try:
            cursor_seq = _decode_events_cursor(cursor)
        except InvalidCursorError as exc:
            raise ProblemDetailsError(
                status=400, title="Invalid Cursor", detail=str(exc)
            ) from exc

    bounds = [v for v in (after_seq, cursor_seq) if v is not None]
    effective_after_seq = max(bounds) if bounds else None

    fetched = await store.get_events(
        run_id, kind=kind, after_seq=effective_after_seq, limit=limit + 1
    )
    page, has_more = fetched[:limit], len(fetched) > limit
    next_cursor = encode_cursor({"seq": page[-1].seq}) if has_more and page else None

    return EventsPage(events=[_event_out(e) for e in page], next_cursor=next_cursor)


@router.get("/runs/{run_id}/detections", response_model=DetectionsPage)
async def list_detections(
    run_id: str, store: Annotated[TraceStore, Depends(get_trace_store)]
) -> DetectionsPage:
    """Most-recently-raised first (TRZ-P5-06) — small enough per run
    (rule-detector fires, not every event) that this skips the query
    API's cursor pagination entirely, matching the replay-bundle
    endpoint's "small enough to just return it all" reasoning below."""
    run = await store.get_run(run_id)
    if run is None:
        raise ProblemDetailsError(
            status=404, title="Not Found", detail=f"no run {run_id}"
        )
    detections = await store.list_detections(run_id)
    return DetectionsPage(detections=[_detection_out(d) for d in detections])


@router.get("/runs/{run_id}/policy-decisions", response_model=PolicyDecisionsPage)
async def list_policy_decisions(
    run_id: str, store: Annotated[TraceStore, Depends(get_trace_store)]
) -> PolicyDecisionsPage:
    """Most-recently-decided first (TRZ-P6-05) — same "small enough to
    just return it all" reasoning as ``list_detections`` above: policy
    decisions accrue only on governed actions, not every event."""
    run = await store.get_run(run_id)
    if run is None:
        raise ProblemDetailsError(
            status=404, title="Not Found", detail=f"no run {run_id}"
        )
    decisions = await store.list_policy_decisions(run_id)
    return PolicyDecisionsPage(decisions=[_policy_decision_out(d) for d in decisions])


# The dashboard's Overview is a pure API consumer (ARCHITECTURE.md §2.3:
# "anything the dashboard computes that matters -- e.g. cost rollups --
# must come from the API instead"), so every number it shows is computed
# here, in one round trip, rather than by fetching runs and summing them
# client-side.
#
# Deliberately a bounded scan over the most recent N runs rather than a
# GROUP BY over the whole table: at MVP corpus scale (ADR-003's "a few
# million rows" ceiling) this is a single indexed read of already-
# maintained `runs.totals` rollups, and it keeps the aggregate identical
# across both TraceStore implementations instead of hand-writing
# dialect-specific aggregate SQL twice. `window_runs` reports how many
# runs actually backed the response, so a caller can tell "0 failures"
# from "0 failures in the last 500 runs". Revisit with a real GROUP BY
# (or a rollup table) when a measured page load says to -- philosophy #7.
_STATS_WINDOW_RUNS = 500
_STATS_RECENT_DETECTIONS = 8
_STATS_POLICY_WINDOW = 500
# The denial *count* above is over the whole policy window; this is just
# how many of those decisions the feed itself renders.
_STATS_RECENT_DECISIONS = 12

_FAILED_RUN_STATUSES = frozenset({"error", "blocked"})
_ACTIVE_RUN_STATUSES = frozenset({"running"})


def _pct_change(current: float, previous: float) -> float | None:
    """None when there's no prior window to compare against — the UI
    renders "no prior data" rather than a meaningless +100%."""
    if previous <= 0:
        return None
    return round(((current - previous) / previous) * 100, 1)


@router.get("/stats", response_model=StatsOut)
async def get_stats(
    store: Annotated[TraceStore, Depends(get_trace_store)],
    days: int | None = None,
    project: str | None = None,
) -> StatsOut:
    """Fleet-wide rollups for the dashboard Overview: run/failure/cost
    counters, a per-day series, cost split by project, the newest
    detections across every run, and this window's change against the
    one before it.

    ``days`` restricts to runs started within the last N days (and
    computes the deltas against the equally-long window before that);
    omitted means the whole bounded scan with no delta baseline.
    """
    runs = await store.list_runs(project_id=project, limit=_STATS_WINDOW_RUNS)

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=days) if days else None
    previous_start = now - timedelta(days=days * 2) if days else None

    in_window: list[RunRow] = []
    previous: list[RunRow] = []
    for run in runs:
        # Stored timestamps are tz-aware (timestamptz); guard anyway so a
        # naive value from a fake store can't raise on comparison.
        started = run.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if window_start is None or started >= window_start:
            in_window.append(run)
        elif previous_start is not None and started >= previous_start:
            previous.append(run)

    daily: dict[str, StatsDailyPoint] = {}
    by_project: dict[str, StatsProjectCost] = {}
    total_cost = 0.0
    failed = 0
    active = 0

    for run in in_window:
        cost = float(run.totals.get("cost_usd", 0.0) or 0.0)
        total_cost += cost
        is_failed = run.status in _FAILED_RUN_STATUSES
        failed += is_failed
        active += run.status in _ACTIVE_RUN_STATUSES

        day = run.started_at.date().isoformat()
        point = daily.get(day) or StatsDailyPoint(
            date=day, runs=0, failed_runs=0, cost_usd=0.0
        )
        daily[day] = StatsDailyPoint(
            date=day,
            runs=point.runs + 1,
            failed_runs=point.failed_runs + is_failed,
            cost_usd=point.cost_usd + cost,
        )

        bucket = by_project.get(run.project_id) or StatsProjectCost(
            project_id=run.project_id, runs=0, cost_usd=0.0
        )
        by_project[run.project_id] = StatsProjectCost(
            project_id=run.project_id,
            runs=bucket.runs + 1,
            cost_usd=bucket.cost_usd + cost,
        )

    prev_failed = sum(1 for r in previous if r.status in _FAILED_RUN_STATUSES)
    prev_cost = sum(float(r.totals.get("cost_usd", 0.0) or 0.0) for r in previous)

    recent_detections = await store.list_recent_detections(
        limit=_STATS_RECENT_DETECTIONS
    )
    decisions = await store.list_recent_policy_decisions(limit=_STATS_POLICY_WINDOW)

    return StatsOut(
        total_runs=len(in_window),
        failed_runs=failed,
        active_runs=active,
        total_cost_usd=round(total_cost, 4),
        policy_denials=sum(1 for d in decisions if d.decision in ("deny", "escalate")),
        total_detections=len(recent_detections),
        window_runs=len(in_window),
        range_days=days,
        deltas=StatsDeltas(
            runs_pct=_pct_change(len(in_window), len(previous)),
            failed_runs_pct=_pct_change(failed, prev_failed),
            cost_pct=_pct_change(total_cost, prev_cost),
        ),
        daily=sorted(daily.values(), key=lambda p: p.date),
        cost_by_project=sorted(
            by_project.values(), key=lambda p: p.cost_usd, reverse=True
        ),
        recent_detections=[_detection_out(d) for d in recent_detections],
        recent_policy_decisions=[
            _policy_decision_out(d) for d in decisions[:_STATS_RECENT_DECISIONS]
        ],
    )


# Bounded event scans behind the Traces / Logs / Tools / Agents surfaces.
# Same reasoning as the stats window above: one `list_recent_events` read
# per request, aggregated here, rather than four bespoke GROUP BY queries
# whose results would then have to agree with each other.
_EVENT_FEED_LIMIT = 200
_TOOL_WINDOW_EVENTS = 1000
_AGENT_WINDOW_EVENTS = 1000


@router.get("/events/recent", response_model=EventsPage)
async def list_recent_events(
    store: Annotated[TraceStore, Depends(get_trace_store)],
    kind: str | None = None,
    limit: int = _EVENT_FEED_LIMIT,
) -> EventsPage:
    """Newest events across every run — the raw trace feed, and (with
    ``kind=sdk.diagnostic``) the SDK's own diagnostic log."""
    rows = await store.list_recent_events(kind=kind, limit=_clamp_limit(limit))
    return EventsPage(events=[_event_out(row) for row in rows], next_cursor=None)


@router.get("/tools", response_model=ToolsPage)
async def list_tools(
    store: Annotated[TraceStore, Depends(get_trace_store)],
) -> ToolsPage:
    """Per-tool rollup derived from recent ``tool.call`` events: call
    count, error count, mean latency, and when it was last used."""
    rows = await store.list_recent_events(kind="tool.call", limit=_TOOL_WINDOW_EVENTS)

    calls: dict[str, int] = {}
    errors: dict[str, int] = {}
    latency_total: dict[str, float] = {}
    side_effect: dict[str, str] = {}
    last_used: dict[str, str] = {}

    for row in rows:
        payload = row.payload
        name = str(payload.get("tool_name") or "unknown")
        calls[name] = calls.get(name, 0) + 1
        if payload.get("status") not in (None, "ok"):
            errors[name] = errors.get(name, 0) + 1
        latency = payload.get("latency_ms")
        if isinstance(latency, (int, float)):
            latency_total[name] = latency_total.get(name, 0.0) + float(latency)
        side_effect.setdefault(name, str(payload.get("side_effect_class") or "unknown"))
        # rows arrive newest-first, so the first sighting is the latest.
        last_used.setdefault(name, row.ts.isoformat())

    tools = [
        ToolStat(
            tool_name=name,
            calls=count,
            errors=errors.get(name, 0),
            avg_latency_ms=round(latency_total.get(name, 0.0) / count, 3),
            side_effect_class=side_effect.get(name, "unknown"),
            last_used=last_used.get(name, ""),
        )
        for name, count in calls.items()
    ]
    tools.sort(key=lambda t: t.calls, reverse=True)
    return ToolsPage(tools=tools, window_events=len(rows))


@router.get("/agents", response_model=AgentsPage)
async def list_agents(
    store: Annotated[TraceStore, Depends(get_trace_store)],
) -> AgentsPage:
    """Per-agent rollup from recent events' ``agent_id``.

    ``unattributed_events`` is reported alongside on purpose: only an
    adapter that can name the acting agent sets ``agent_id`` (CrewAI's
    does, per-role; the LangGraph adapter leaves it null because a graph
    node isn't an agent identity), so an empty list here means "nothing
    attributed", not "nothing ran".
    """
    rows = await store.list_recent_events(limit=_AGENT_WINDOW_EVENTS)

    events: dict[str, int] = {}
    runs: dict[str, set[str]] = {}
    last_seen: dict[str, str] = {}
    unattributed = 0

    for row in rows:
        if not row.agent_id:
            unattributed += 1
            continue
        events[row.agent_id] = events.get(row.agent_id, 0) + 1
        runs.setdefault(row.agent_id, set()).add(row.run_id)
        last_seen.setdefault(row.agent_id, row.ts.isoformat())

    agents = [
        AgentStat(
            agent_id=agent_id,
            events=count,
            runs=len(runs.get(agent_id, set())),
            last_seen=last_seen.get(agent_id, ""),
        )
        for agent_id, count in events.items()
    ]
    agents.sort(key=lambda a: a.events, reverse=True)
    return AgentsPage(
        agents=agents, window_events=len(rows), unattributed_events=unattributed
    )


@router.get("/projects", response_model=ProjectsPage)
async def list_projects(
    store: Annotated[TraceStore, Depends(get_trace_store)],
) -> ProjectsPage:
    """Projects that actually have runs — backs the dashboard's project
    filter. Derived from the run window rather than the `projects` table
    so the filter only ever offers values that will return something."""
    runs = await store.list_runs(limit=_STATS_WINDOW_RUNS)
    counts: dict[str, int] = {}
    for run in runs:
        counts[run.project_id] = counts.get(run.project_id, 0) + 1
    projects = [
        ProjectOut(project_id=project_id, runs=count)
        for project_id, count in counts.items()
    ]
    projects.sort(key=lambda p: p.runs, reverse=True)
    return ProjectsPage(projects=projects)


_BUNDLE_PAGE_SIZE = 1000


async def _all_events(store: TraceStore, run_id: str) -> list[EventRow]:
    """Every event for one run, in seq order, ignoring the query API's own
    page-size cap (that cap is a client-pagination concern; a replay
    bundle is a single complete document — REPLAY_ENGINE.md §7). Pages
    internally so this works the same against Postgres (fetch-limited)
    and the in-memory fake."""
    events: list[EventRow] = []
    after_seq: int | None = None
    while True:
        page = await store.get_events(
            run_id, after_seq=after_seq, limit=_BUNDLE_PAGE_SIZE
        )
        if not page:
            break
        events.extend(page)
        after_seq = page[-1].seq
        if len(page) < _BUNDLE_PAGE_SIZE:
            break
    return events


def _bundle_etag(run_id: str, events: list[EventRow]) -> str:
    """Cheap content identity: (run_id, count, last event_id) changes
    whenever the event set changes, without hashing every payload."""
    last_event_id = events[-1].event_id if events else ""
    basis = f"{run_id}:{len(events)}:{last_event_id}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


@router.get("/runs/{run_id}/replay-bundle")
async def get_replay_bundle(
    run_id: str, store: Annotated[TraceStore, Depends(get_trace_store)]
) -> Response:
    """NDJSON: line 1 a manifest (run metadata, event count, deduplicated
    blob manifest), then one line per event in seq order — everything a
    replay session (SDK.md's ``trazo.replay``) needs, in one document
    (REPLAY_ENGINE.md §7). Immutable/cacheable forever *once a run is no
    longer ``running``*: a still-running run's bundle would otherwise be
    cached as if complete, which it isn't yet.
    """
    run = await store.get_run(run_id)
    if run is None:
        raise ProblemDetailsError(
            status=404, title="Not Found", detail=f"no run {run_id}"
        )

    events = await _all_events(store, run_id)

    blob_bytes_by_sha: dict[str, int] = {}
    for event in events:
        for blob in event.blobs:
            blob_bytes_by_sha[blob["sha256"]] = blob["bytes"]

    manifest = {
        "schema": "trazo.replay-bundle.v1",
        "run_id": run.run_id,
        "project_id": run.project_id,
        "framework": run.framework,
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "tags": run.tags,
        "totals": run.totals,
        "event_count": len(events),
        "blob_manifest": [
            {"sha256": sha, "bytes": n} for sha, n in sorted(blob_bytes_by_sha.items())
        ],
    }

    lines = [json.dumps(manifest, sort_keys=True)]
    lines.extend(_event_out(e).model_dump_json() for e in events)
    body = ("\n".join(lines) + "\n").encode("utf-8")

    headers = {"ETag": f'"{_bundle_etag(run_id, events)}"'}
    headers["Cache-Control"] = (
        "public, max-age=31536000, immutable" if run.status != "running" else "no-store"
    )

    return Response(content=body, media_type="application/x-ndjson", headers=headers)


@router.get("/blobs/{sha256}")
async def get_blob(
    sha256: str, blob_store: Annotated[BlobStore, Depends(get_blob_store)]
) -> Response:
    """Immutable, cacheable (API_SPEC.md "Live"/"Query"). Every blob this
    control plane writes is JSON (store_worker.py's offload path always
    encodes offloaded fields as JSON before calling BlobStore.put) — the
    filesystem store doesn't track per-blob content_type, so this is a
    fixed value, not a lookup, until the blobs projection table (DATABASE.md
    §2) is actually populated by something.
    """
    try:
        data = await blob_store.get(sha256)
    except BlobNotFoundError as exc:
        raise ProblemDetailsError(
            status=404, title="Not Found", detail=f"no blob {sha256}"
        ) from exc
    return Response(
        content=data,
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
