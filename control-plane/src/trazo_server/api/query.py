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
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from trazo_server.api.cursors import InvalidCursorError, decode_cursor, encode_cursor
from trazo_server.api.deps import get_blob_store, get_trace_store
from trazo_server.api.problem_details import ProblemDetailsError
from trazo_server.errors import BlobNotFoundError
from trazo_server.store.blob_store import BlobStore
from trazo_server.store.rows import DetectionRow, EventRow, RunRow
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
