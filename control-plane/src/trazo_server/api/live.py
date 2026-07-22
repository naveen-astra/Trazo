"""Live API: GET /v1/live/runs/{run_id}, GET /v1/live/firehose (API_SPEC.md
"Live").

SSE, sourced by polling TraceStore for new events past the client's last-
seen position — simpler and more robust than a Redis-native fanout at MVP
scale, and reuses the exact read path the query API already exercises.
Per-run streams close naturally once ``run.finished`` is observed (a
terminal run can never produce more events, matching the "immutable once
terminal" language API_SPEC.md uses for the replay-bundle endpoint); the
firehose has no natural end and stays open until the client disconnects.

The streaming generators take a plain ``is_disconnected`` callable rather
than a ``Request`` — decouples them from FastAPI/Starlette so they're
directly unit-testable (a fake callable, no live HTTP round-trip needed
for the firehose, which never terminates on its own).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from trazo_server.api.deps import get_trace_store
from trazo_server.metrics import SSE_CLIENTS
from trazo_server.store.rows import EventRow
from trazo_server.store.trace_store import TraceStore

router = APIRouter(prefix="/v1")

POLL_INTERVAL_SECONDS = 0.5


def _event_out(event: EventRow) -> dict[str, Any]:
    return {
        "run_id": event.run_id,
        "seq": event.seq,
        "event_id": event.event_id,
        "kind": event.kind,
        "ts": event.ts.isoformat(),
        "step_id": event.step_id,
        "agent_id": event.agent_id,
        "fingerprint": event.fingerprint,
        "payload": event.payload,
        "blobs": event.blobs,
    }


def _sse_message(event_id: str, data: dict[str, Any]) -> str:
    # Default ("message") event type only — `kind` is already inside
    # `data`, and keeping SSE-level `event:` types in sync with EVENTS.md's
    # kind list on the client would be a second place to maintain the
    # same information for no benefit.
    body = json.dumps(data, separators=(",", ":"))
    return f"id: {event_id}\ndata: {body}\n\n"


async def stream_run_events(
    store: TraceStore,
    run_id: str,
    *,
    after_seq: int | None,
    is_disconnected: Callable[[], Awaitable[bool]],
    poll_interval: float = POLL_INTERVAL_SECONDS,
) -> AsyncIterator[str]:
    """Yields SSE messages for one run's events, oldest first, resuming
    from ``after_seq``. Returns (closes the stream) once ``run.finished``
    is observed, or the client disconnects."""
    last_seq = after_seq
    while True:
        if await is_disconnected():
            return
        events = await store.get_events(run_id, after_seq=last_seq, limit=100)
        for event in events:
            last_seq = event.seq
            yield _sse_message(str(event.seq), _event_out(event))
            if event.kind == "run.finished":
                return
        if not events:
            await asyncio.sleep(poll_interval)


async def stream_project_events(
    store: TraceStore,
    project_id: str,
    *,
    after_event_id: str | None,
    is_disconnected: Callable[[], Awaitable[bool]],
    poll_interval: float = POLL_INTERVAL_SECONDS,
) -> AsyncIterator[str]:
    """Yields SSE messages for every event across every run in a project,
    ordered by event_id (ULID — globally sortable, unlike per-run seq).
    Never terminates on its own; only a client disconnect ends it."""
    last_event_id = after_event_id
    while True:
        if await is_disconnected():
            return
        events = await store.get_project_events(
            project_id, after_event_id=last_event_id, limit=100
        )
        for event in events:
            last_event_id = event.event_id
            yield _sse_message(event.event_id, _event_out(event))
        if not events:
            await asyncio.sleep(poll_interval)


@router.get("/live/runs/{run_id}")
async def live_run(
    run_id: str,
    request: Request,
    store: Annotated[TraceStore, Depends(get_trace_store)],
) -> StreamingResponse:
    last_event_id = request.headers.get("last-event-id")
    after_seq = int(last_event_id) if last_event_id else None

    async def _generator() -> AsyncIterator[str]:
        SSE_CLIENTS.labels(endpoint="runs").inc()
        try:
            async for chunk in stream_run_events(
                store,
                run_id,
                after_seq=after_seq,
                is_disconnected=request.is_disconnected,
            ):
                yield chunk
        finally:
            SSE_CLIENTS.labels(endpoint="runs").dec()

    return StreamingResponse(_generator(), media_type="text/event-stream")


@router.get("/live/firehose")
async def live_firehose(
    project: str,
    request: Request,
    store: Annotated[TraceStore, Depends(get_trace_store)],
) -> StreamingResponse:
    after_event_id = request.headers.get("last-event-id")

    async def _generator() -> AsyncIterator[str]:
        SSE_CLIENTS.labels(endpoint="firehose").inc()
        try:
            async for chunk in stream_project_events(
                store,
                project,
                after_event_id=after_event_id,
                is_disconnected=request.is_disconnected,
            ):
                yield chunk
        finally:
            SSE_CLIENTS.labels(endpoint="firehose").dec()

    return StreamingResponse(_generator(), media_type="text/event-stream")
