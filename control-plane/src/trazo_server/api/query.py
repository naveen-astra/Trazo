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
import math
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from trazo_server.api.cursors import InvalidCursorError, decode_cursor, encode_cursor
from trazo_server.api.deps import get_blob_store, get_trace_store
from trazo_server.api.problem_details import ProblemDetailsError
from trazo_server.api.projects import resolve_project_id
from trazo_server.errors import BlobNotFoundError
from trazo_server.store.blob_store import BlobStore
from trazo_server.store.rows import (
    DetectionRow,
    EventRow,
    PolicyDecisionRow,
    ReplayReportRow,
    RunRow,
)
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


class DetectorCount(BaseModel):
    detector: str
    count: int


class PolicyDenialCount(BaseModel):
    policy_id: str
    count: int


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
    # Unit-economics/quality framing the Overview leads with — every field
    # below is a ratio or percentile over numbers this handler already has
    # in memory, never a second authoritative source of truth for the same
    # count (ARCHITECTURE.md §2.3: the dashboard stays a pure API consumer,
    # so this handler does the arithmetic once instead of every client).
    success_rate_pct: float | None
    avg_cost_per_run_usd: float | None
    duration_p50_ms: float | None
    duration_p95_ms: float | None
    detections_by_detector: list[DetectorCount]
    denials_by_policy: list[PolicyDenialCount]


class ToolStat(BaseModel):
    tool_name: str
    calls: int
    errors: int
    avg_latency_ms: float
    # Mean latency alone hides how bad the tail gets; p95 is what actually
    # answers "should I be worried about this tool" the way avg cannot.
    p50_latency_ms: float
    p95_latency_ms: float
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


class ModelStat(BaseModel):
    provider: str
    model: str
    calls: int
    cost_usd: float
    tokens_in: int
    tokens_out: int
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    last_used: str


class ModelsPage(BaseModel):
    models: list[ModelStat]
    window_events: int


class ProjectOut(BaseModel):
    project_id: str
    # The name the SDK was configured with ("research-assistant"), which
    # is what a human recognises; project_id is a hash of it. Falls back
    # to the id only if a run somehow predates its projects row.
    name: str
    runs: int


class ProjectsPage(BaseModel):
    projects: list[ProjectOut]


class DetectionsFeedPage(BaseModel):
    """A dedicated, filterable, cross-run feed for the Incidents page —
    distinct from DetectionsPage (one run's detections, unfiltered,
    unbounded) and from StatsOut.recent_detections (fixed-size, for the
    Overview's glanceable summary only)."""

    detections: list[DetectionOut]
    window_scanned: int


class PolicyDecisionsFeedPage(BaseModel):
    """Same relationship to PolicyDecisionsPage/StatsOut.recent_policy_decisions
    as DetectionsFeedPage has to detections above."""

    decisions: list[PolicyDecisionOut]
    window_scanned: int


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile over an already-sorted (ascending) list.

    Not interpolated — this deployment's windows are small enough (a few
    hundred to a thousand samples) that nearest-rank is both simpler and
    exactly reproducible without a floating-point interpolation step.
    """
    if not sorted_values:
        return 0.0
    index = max(0, math.ceil(pct / 100 * len(sorted_values)) - 1)
    return sorted_values[min(index, len(sorted_values) - 1)]


def _clamp_limit(limit: int, max_limit: int = _MAX_LIMIT) -> int:
    if not (1 <= limit <= max_limit):
        raise ProblemDetailsError(
            status=400,
            title="Invalid Limit",
            detail=f"limit must be between 1 and {max_limit}, got {limit}",
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
        project_id=await resolve_project_id(store, project),
        status=status,
        limit=limit + 1,
        before=before,
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


class DivergenceOut(BaseModel):
    kind: str
    reason: str
    expected_seq: int
    expected_event_id: str
    expected_fingerprint: str
    live_fingerprint: str


class ReplayReportOut(BaseModel):
    run_id: str
    boundary_fidelity: float
    state_fidelity: float
    matched: int
    reordered: int
    divergences: list[DivergenceOut]
    replay_overhead: float | None
    verified_at: str


def _replay_report_out(report: ReplayReportRow) -> ReplayReportOut:
    return ReplayReportOut(
        run_id=report.run_id,
        boundary_fidelity=report.boundary_fidelity,
        state_fidelity=report.state_fidelity,
        matched=report.matched,
        reordered=report.reordered,
        divergences=[DivergenceOut(**d) for d in report.divergences],
        replay_overhead=report.replay_overhead,
        verified_at=report.verified_at.isoformat(),
    )


@router.get("/runs/{run_id}/replay-report", response_model=ReplayReportOut)
async def get_replay_report(
    run_id: str, store: Annotated[TraceStore, Depends(get_trace_store)]
) -> ReplayReportOut:
    """The most recent ``trazo verify <run_id>`` result for this run.

    404 when it has never been verified — an honest "not yet checked"
    rather than a fabricated report (there is no way to compute fidelity
    from stored events alone; it requires actually re-driving the
    original entrypoint, which only the SDK's ReplaySession can do, and
    that result reaches here only via POST /v1/runs/{run_id}/replay-report
    when a caller chooses to submit it — see ingest.py)."""
    report = await store.get_replay_report(run_id)
    if report is None:
        raise ProblemDetailsError(
            status=404,
            title="Not Found",
            detail=f"run {run_id} has not been verified — run `trazo verify {run_id}`",
        )
    return _replay_report_out(report)


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
# A separate, larger detections scan for total_detections/
# detections_by_detector: _STATS_RECENT_DETECTIONS (8) is sized for the
# Overview's glanceable list, not for an accurate count — reusing it for
# both made total_detections silently mean "min(actual count, 8)".
_STATS_DETECTIONS_WINDOW = 500

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
    runs = await store.list_runs(
        project_id=await resolve_project_id(store, project),
        limit=_STATS_WINDOW_RUNS,
    )

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

    # Sized for an accurate total, not for display — recent_detections
    # below stays capped at _STATS_RECENT_DETECTIONS for the Overview's
    # glanceable list; this larger scan backs total_detections and the
    # by-detector breakdown, which need the real count, not the display cap.
    detections_in_window = await store.list_recent_detections(
        limit=_STATS_DETECTIONS_WINDOW
    )
    recent_detections = detections_in_window[:_STATS_RECENT_DETECTIONS]
    decisions = await store.list_recent_policy_decisions(limit=_STATS_POLICY_WINDOW)

    durations = sorted(
        float(r.totals["duration_ms"])
        for r in in_window
        if isinstance(r.totals.get("duration_ms"), (int, float))
    )

    detector_counts: dict[str, int] = {}
    for detection in detections_in_window:
        detector_counts[detection.detector] = (
            detector_counts.get(detection.detector, 0) + 1
        )

    denial_counts: dict[str, int] = {}
    for decision in decisions:
        if decision.decision in ("deny", "escalate"):
            denial_counts[decision.policy_id] = (
                denial_counts.get(decision.policy_id, 0) + 1
            )

    window_runs = len(in_window)

    return StatsOut(
        total_runs=window_runs,
        failed_runs=failed,
        active_runs=active,
        total_cost_usd=round(total_cost, 4),
        policy_denials=sum(1 for d in decisions if d.decision in ("deny", "escalate")),
        total_detections=len(detections_in_window),
        window_runs=window_runs,
        range_days=days,
        deltas=StatsDeltas(
            runs_pct=_pct_change(window_runs, len(previous)),
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
        success_rate_pct=(
            round(100 * (window_runs - failed) / window_runs, 1)
            if window_runs > 0
            else None
        ),
        avg_cost_per_run_usd=(
            round(total_cost / window_runs, 4) if window_runs > 0 else None
        ),
        duration_p50_ms=round(_percentile(durations, 50), 1) if durations else None,
        duration_p95_ms=round(_percentile(durations, 95), 1) if durations else None,
        detections_by_detector=sorted(
            (DetectorCount(detector=k, count=v) for k, v in detector_counts.items()),
            key=lambda d: d.count,
            reverse=True,
        ),
        denials_by_policy=sorted(
            (PolicyDenialCount(policy_id=k, count=v) for k, v in denial_counts.items()),
            key=lambda d: d.count,
            reverse=True,
        ),
    )


# Bounded event scans behind the Traces / Logs / Tools / Agents surfaces.
# Same reasoning as the stats window above: one `list_recent_events` read
# per request, aggregated here, rather than four bespoke GROUP BY queries
# whose results would then have to agree with each other.
_EVENT_FEED_LIMIT = 200
_TOOL_WINDOW_EVENTS = 1000
_AGENT_WINDOW_EVENTS = 1000
_MODEL_WINDOW_EVENTS = 1000
# The Incidents/Policy pages' dedicated feeds: scanned wider than they're
# ever returned so a project/detector/severity filter still has enough
# rows to draw from, distinct from _STATS_DETECTIONS_WINDOW/_STATS_POLICY_
# WINDOW above (those back StatsOut's counts, not these pages' listings).
_DETECTIONS_FEED_SCAN = 500
_DETECTIONS_FEED_DEFAULT_LIMIT = 50
_DETECTIONS_FEED_MAX_LIMIT = 200
_POLICY_FEED_SCAN = 500
_POLICY_FEED_DEFAULT_LIMIT = 50
_POLICY_FEED_MAX_LIMIT = 200
_PROJECT_JOIN_RUNS = 500


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
    count, error count, latency (mean + p50/p95), and when it was last
    used."""
    rows = await store.list_recent_events(kind="tool.call", limit=_TOOL_WINDOW_EVENTS)

    calls: dict[str, int] = {}
    errors: dict[str, int] = {}
    latencies: dict[str, list[float]] = {}
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
            latencies.setdefault(name, []).append(float(latency))
        side_effect.setdefault(name, str(payload.get("side_effect_class") or "unknown"))
        # rows arrive newest-first, so the first sighting is the latest.
        last_used.setdefault(name, row.ts.isoformat())

    tools = []
    for name, count in calls.items():
        tool_latencies = sorted(latencies.get(name, []))
        tools.append(
            ToolStat(
                tool_name=name,
                calls=count,
                errors=errors.get(name, 0),
                avg_latency_ms=round(sum(tool_latencies) / len(tool_latencies), 3)
                if tool_latencies
                else 0.0,
                p50_latency_ms=round(_percentile(tool_latencies, 50), 3),
                p95_latency_ms=round(_percentile(tool_latencies, 95), 3),
                side_effect_class=side_effect.get(name, "unknown"),
                last_used=last_used.get(name, ""),
            )
        )
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


@router.get("/models", response_model=ModelsPage)
async def list_models(
    store: Annotated[TraceStore, Depends(get_trace_store)],
) -> ModelsPage:
    """Per-(provider, model) rollup derived from recent ``llm.call``
    events — the standard LLM-ops "where is the money going" view, sorted
    by spend rather than volume since cost is what this page exists to
    answer."""
    rows = await store.list_recent_events(kind="llm.call", limit=_MODEL_WINDOW_EVENTS)

    calls: dict[tuple[str, str], int] = {}
    cost: dict[tuple[str, str], float] = {}
    tokens_in: dict[tuple[str, str], int] = {}
    tokens_out: dict[tuple[str, str], int] = {}
    latencies: dict[tuple[str, str], list[float]] = {}
    last_used: dict[tuple[str, str], str] = {}

    for row in rows:
        payload = row.payload
        key = (
            str(payload.get("provider") or "unknown"),
            str(payload.get("model") or "unknown"),
        )
        calls[key] = calls.get(key, 0) + 1
        cost[key] = cost.get(key, 0.0) + float(payload.get("cost_usd", 0.0) or 0.0)
        tokens_in[key] = tokens_in.get(key, 0) + int(payload.get("tokens_in", 0) or 0)
        tokens_out[key] = tokens_out.get(key, 0) + int(
            payload.get("tokens_out", 0) or 0
        )
        latency = payload.get("latency_ms")
        if isinstance(latency, (int, float)):
            latencies.setdefault(key, []).append(float(latency))
        last_used.setdefault(key, row.ts.isoformat())

    models = []
    for key, count in calls.items():
        provider, model = key
        key_latencies = sorted(latencies.get(key, []))
        models.append(
            ModelStat(
                provider=provider,
                model=model,
                calls=count,
                cost_usd=round(cost.get(key, 0.0), 4),
                tokens_in=tokens_in.get(key, 0),
                tokens_out=tokens_out.get(key, 0),
                avg_latency_ms=round(sum(key_latencies) / len(key_latencies), 3)
                if key_latencies
                else 0.0,
                p50_latency_ms=round(_percentile(key_latencies, 50), 3),
                p95_latency_ms=round(_percentile(key_latencies, 95), 3),
                last_used=last_used.get(key, ""),
            )
        )
    models.sort(key=lambda m: m.cost_usd, reverse=True)
    return ModelsPage(models=models, window_events=len(rows))


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
    names = await store.list_project_names()
    projects = [
        ProjectOut(
            project_id=project_id,
            name=names.get(project_id, project_id),
            runs=count,
        )
        for project_id, count in counts.items()
    ]
    projects.sort(key=lambda p: p.runs, reverse=True)
    return ProjectsPage(projects=projects)


async def _run_ids_for_project(store: TraceStore, project_id: str) -> set[str]:
    """Detections/policy decisions only carry ``run_id``, not
    ``project_id`` — narrowing either feed to one project means joining
    against that project's runs first, the same technique
    ``get_project_events`` already uses at the store layer."""
    runs = await store.list_runs(project_id=project_id, limit=_PROJECT_JOIN_RUNS)
    return {r.run_id for r in runs}


@router.get("/detections", response_model=DetectionsFeedPage)
async def list_detections_feed(
    store: Annotated[TraceStore, Depends(get_trace_store)],
    project: str | None = None,
    detector: str | None = None,
    severity: str | None = None,
    limit: int = _DETECTIONS_FEED_DEFAULT_LIMIT,
) -> DetectionsFeedPage:
    """Cross-run, filterable detection feed for the Incidents page.

    Distinct from StatsOut.recent_detections (fixed at 8, for the
    Overview's glanceable summary) and from GET /runs/{id}/detections
    (one run, unfiltered) — this is the "show me more than a handful,
    narrowed down" surface neither of those is meant to be.
    """
    limit = _clamp_limit(limit, _DETECTIONS_FEED_MAX_LIMIT)
    rows = await store.list_recent_detections(limit=_DETECTIONS_FEED_SCAN)

    run_ids: set[str] | None = None
    if project is not None:
        resolved = await resolve_project_id(store, project)
        run_ids = await _run_ids_for_project(store, resolved) if resolved else set()

    filtered = [
        d
        for d in rows
        if (run_ids is None or d.run_id in run_ids)
        and (detector is None or d.detector == detector)
        and (severity is None or d.severity == severity)
    ]
    return DetectionsFeedPage(
        detections=[_detection_out(d) for d in filtered[:limit]],
        window_scanned=len(rows),
    )


@router.get("/policy-decisions", response_model=PolicyDecisionsFeedPage)
async def list_policy_decisions_feed(
    store: Annotated[TraceStore, Depends(get_trace_store)],
    project: str | None = None,
    decision: str | None = None,
    policy_id: str | None = None,
    limit: int = _POLICY_FEED_DEFAULT_LIMIT,
) -> PolicyDecisionsFeedPage:
    """Cross-run, filterable policy-decision feed for the Policy page —
    same relationship to StatsOut.recent_policy_decisions and
    GET /runs/{id}/policy-decisions as list_detections_feed has above."""
    limit = _clamp_limit(limit, _POLICY_FEED_MAX_LIMIT)
    rows = await store.list_recent_policy_decisions(limit=_POLICY_FEED_SCAN)

    run_ids: set[str] | None = None
    if project is not None:
        resolved = await resolve_project_id(store, project)
        run_ids = await _run_ids_for_project(store, resolved) if resolved else set()

    filtered = [
        d
        for d in rows
        if (run_ids is None or d.run_id in run_ids)
        and (decision is None or d.decision == decision)
        and (policy_id is None or d.policy_id == policy_id)
    ]
    return PolicyDecisionsFeedPage(
        decisions=[_policy_decision_out(d) for d in filtered[:limit]],
        window_scanned=len(rows),
    )


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
