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
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from trazo_server.api.deps import get_trace_store, require_viewer
from trazo_server.api.projects import resolve_project_id
from trazo_server.metrics import SSE_CLIENTS
from trazo_server.store.rows import EventRow
from trazo_server.store.trace_store import TraceStore

router = APIRouter(prefix="/v1", dependencies=[Depends(require_viewer)])

POLL_INTERVAL_SECONDS = 0.5
# How long a per-run stream stays open after `run.finished`. Detections are
# raised by a separate worker and can land a moment after the run ends --
# measured at 0.1-2.3 s on the demo stack -- and closing on run.finished
# alone dropped every one of them.
LATE_EVENT_GRACE_SECONDS = 3.0
# How far behind its cursor the firehose re-reads each poll, for rows whose
# insert committed after a later-numbered one. Commit reordering spans only
# transactions in flight at the same moment, so this is generous.
FIREHOSE_LOOKBACK_ROWS = 1000

Position = tuple[int, int]


def _event_out(event: EventRow) -> dict[str, Any]:
    return {
        "run_id": event.run_id,
        "seq": event.seq,
        "sub_seq": event.sub_seq,
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


def _format_position(position: Position | None) -> str:
    return "" if position is None else f"{position[0]}.{position[1]}"


def parse_resume_position(last_event_id: str | None) -> tuple[int, int | None] | None:
    """An SSE ``Last-Event-ID``: ``"<seq>.<sub_seq>"``, or a bare ``"<seq>"``
    from a client connected before sub_seq existed. Anything else restarts
    the stream from the beginning rather than failing the request."""
    if not last_event_id:
        return None
    head, _, tail = last_event_id.partition(".")
    try:
        return int(head), (int(tail) if tail else None)
    except ValueError:
        return None


async def stream_run_events(
    store: TraceStore,
    run_id: str,
    *,
    after: tuple[int, int | None] | None,
    is_disconnected: Callable[[], Awaitable[bool]],
    poll_interval: float = POLL_INTERVAL_SECONDS,
    late_event_grace: float = LATE_EVENT_GRACE_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> AsyncIterator[str]:
    """Yields SSE messages for one run's events, oldest first, resuming
    after ``after``. Closes ``late_event_grace`` seconds after
    ``run.finished``, or when the client disconnects.

    Two reads per poll. Events after the cursor, in (seq, sub_seq) order,
    are the bulk of it. But a server event (a detection, a policy decision)
    attaches right after the agent event that caused it, and is often
    written *after* the stream has already moved past that point, so a
    cursor alone would never send it. Each poll therefore also re-reads
    the run's server events -- a handful per run -- and sends any not yet
    seen. Every message's SSE id is the stream's current cursor, so a
    reconnect resumes from the right place whichever kind it was.
    """
    cursor: tuple[int, int | None] | None = after
    sent_server_ids: set[str] = set()
    finished_at: float | None = None

    if after is not None:
        # Resuming: server events at or behind the resume point were sent
        # on the previous connection.
        resume = (after[0], after[1] if after[1] is not None else 2**31)
        for event in await store.get_server_events(run_id):
            if (event.seq, event.sub_seq) <= resume:
                sent_server_ids.add(event.event_id)

    while True:
        if await is_disconnected():
            return
        sent_any = False

        events = await store.get_events(
            run_id,
            after_seq=None if cursor is None else cursor[0],
            after_sub_seq=None if cursor is None else cursor[1],
            limit=100,
        )
        for event in events:
            cursor = (event.seq, event.sub_seq)
            if event.sub_seq > 0:
                if event.event_id in sent_server_ids:
                    continue
                sent_server_ids.add(event.event_id)
            yield _sse_message(_format_position(cursor), _event_out(event))
            sent_any = True
            if event.kind == "run.finished" and finished_at is None:
                finished_at = clock()

        for event in await store.get_server_events(run_id):
            if event.event_id in sent_server_ids:
                continue
            sent_server_ids.add(event.event_id)
            id_position = cursor if cursor is not None else (event.seq, event.sub_seq)
            yield _sse_message(
                _format_position((id_position[0], id_position[1] or 0)),
                _event_out(event),
            )
            sent_any = True

        if finished_at is not None and clock() - finished_at >= late_event_grace:
            return
        if not sent_any:
            await asyncio.sleep(poll_interval)


def firehose_resume(
    last_event_id: str | None, *, tail: bool
) -> tuple[int | None, bool]:
    """The firehose's resume position from an SSE ``Last-Event-ID``, and
    whether to start at the head.

    The id is an ``ingest_seq``. One that is not a number is an
    ``event_id`` cursor from a client connected before the firehose paged
    on storage order: it cannot be mapped onto the new order, so the stream
    starts at the head rather than replaying the whole history.
    """
    if not last_event_id:
        return None, tail
    try:
        return int(last_event_id), tail
    except ValueError:
        return None, True


async def stream_project_events(
    store: TraceStore,
    project: str | None,
    *,
    after: int | None,
    is_disconnected: Callable[[], Awaitable[bool]],
    tail: bool = False,
    poll_interval: float = POLL_INTERVAL_SECONDS,
    lookback: int = FIREHOSE_LOOKBACK_ROWS,
) -> AsyncIterator[str]:
    """Yields SSE messages for every event across every run in a project,
    in the order the store saved them (``ingest_seq``). ``project=None``
    streams every project -- what the dashboard's Overview subscribes to
    when no project filter is set. Never terminates on its own; only a
    client disconnect ends it.

    Paged by ``ingest_seq``, never by ``event_id``: an id carries the clock
    of the machine that minted it, so with an agent's clock ahead of the
    server's, every detection the server minted sorted behind the cursor
    and was never delivered -- critical-incident notifications included.

    ``ingest_seq`` is assigned on insert but becomes visible on commit, and
    two concurrent transactions can commit out of number order. So each
    poll re-reads ``lookback`` rows behind the cursor and skips the ones
    already sent: a row that becomes visible late, below the cursor, is
    still delivered, exactly once.

    ``project`` may be a ``project_id`` or the human project name; it is
    re-resolved on every poll until it maps to a known id. Resolving once
    at subscribe time is not enough for a stream that outlives the
    lookup: a subscriber that connects *before* the project's first event
    finds no name to match, and a one-shot resolution would leave it
    filtering on a value that can never match -- silently delivering
    nothing forever.

    ``tail`` starts the cursor at the current head, so the client is sent
    only events that arrive after it connected. ``after`` always wins over
    it: that carries the SSE ``Last-Event-ID`` resume position, and
    silently skipping to the head on reconnect would drop exactly the
    events the resume exists to recover.
    """
    project_id = await resolve_project_id(store, project)
    cursor = after
    if cursor is None and tail:
        cursor = await store.latest_ingest_seq(project_id)
    cursor = cursor or 0

    sent: set[int] = set()
    if cursor > 0:
        # Resuming or tailing: everything at or below the cursor counts as
        # already delivered, so the look-behind window does not resend it.
        for row in await store.get_project_events(
            project_id, after_ingest_seq=max(cursor - lookback, 0), limit=lookback
        ):
            if row.ingest_seq <= cursor:
                sent.add(row.ingest_seq)

    while True:
        if await is_disconnected():
            return
        if project_id is not None and not project_id.startswith("proj_"):
            project_id = await resolve_project_id(store, project)
        floor = max(cursor - lookback, 0)
        sent = {seq for seq in sent if seq > floor}
        events = await store.get_project_events(
            project_id,
            after_ingest_seq=floor,
            exclude_ingest_seqs=frozenset(sent),
            limit=100,
        )
        for event in events:
            sent.add(event.ingest_seq)
            cursor = max(cursor, event.ingest_seq)
            yield _sse_message(str(cursor), _event_out(event))
        if not events:
            await asyncio.sleep(poll_interval)


@router.get("/live/runs/{run_id}")
async def live_run(
    run_id: str,
    request: Request,
    store: Annotated[TraceStore, Depends(get_trace_store)],
) -> StreamingResponse:
    after = parse_resume_position(request.headers.get("last-event-id"))

    async def _generator() -> AsyncIterator[str]:
        SSE_CLIENTS.labels(endpoint="runs").inc()
        try:
            async for chunk in stream_run_events(
                store,
                run_id,
                after=after,
                is_disconnected=request.is_disconnected,
                # Read at call time, not bound as a default, so it is
                # adjustable (tests shorten it).
                late_event_grace=LATE_EVENT_GRACE_SECONDS,
            ):
                yield chunk
        finally:
            SSE_CLIENTS.labels(endpoint="runs").dec()

    return StreamingResponse(_generator(), media_type="text/event-stream")


@router.get("/live/firehose")
async def live_firehose(
    request: Request,
    store: Annotated[TraceStore, Depends(get_trace_store)],
    project: str | None = None,
    tail: bool = False,
) -> StreamingResponse:
    after, tail = firehose_resume(request.headers.get("last-event-id"), tail=tail)

    async def _generator() -> AsyncIterator[str]:
        SSE_CLIENTS.labels(endpoint="firehose").inc()
        try:
            async for chunk in stream_project_events(
                store,
                project,
                after=after,
                is_disconnected=request.is_disconnected,
                tail=tail,
            ):
                yield chunk
        finally:
            SSE_CLIENTS.labels(endpoint="firehose").dec()

    return StreamingResponse(_generator(), media_type="text/event-stream")
