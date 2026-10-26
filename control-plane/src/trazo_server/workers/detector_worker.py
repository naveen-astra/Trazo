"""Detector worker: bus consumer -> per-run RunWindow -> Detector dispatch
(TRZ-P5-03, AI_DEBUGGER.md §2).

Same consumer-group shape as ``store_worker.py`` (its own separate group
on the same ``EVENTS_STREAM`` — Redis Streams lets multiple independent
consumer groups each track their own position over one stream), but
purely in-memory: windows are rebuilt from ``TraceStore`` on startup
(``rebuild_running_windows``), never persisted themselves.

Turning a ``Detection`` into a persisted, streamed ``detection.raised``
event is deliberately *not* this module's job: unlike ``policy.decision``
(recorded client-side, by the SDK's own recorder, using the same per-run
seq counter every other event uses), a detection is discovered
server-side — this worker has no access to that seq counter, and
minting one safely needs a store-side reservation this task doesn't add
(TRZ-P5-06 owns "detection.raised -> projections", including that). For
now, every ``Detection`` a detector produces is handed to an injectable
``on_detection`` callback (default: structured log) — P5-06 replaces the
default with the real persistence path without touching this worker.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import structlog
from pydantic import ValidationError

from trazo_server.bus.protocol import BUS_BLOCK_MS, BusMessage, EventBus
from trazo_server.detectors.base import Detection, Detector, RunWindow
from trazo_server.drift import DriftDetector
from trazo_server.events import Event, EventAdapter
from trazo_server.store.rows import EventRow, RunRow
from trazo_server.store.trace_store import TraceStore
from trazo_server.topics import DETECTOR_WORKER_GROUP, EVENTS_STREAM

log = structlog.get_logger(__name__)

OnDetection = Callable[[Event, Detection], Awaitable[None]]


async def _log_detection(event: Event, detection: Detection) -> None:
    log.info(
        "detector.raised",
        detector=detection.detector,
        severity=detection.severity,
        run_id=event.run_id,
        evidence_event_ids=detection.evidence_event_ids,
    )


def _event_row_to_event(run: RunRow, row: EventRow) -> Event | None:
    """Reconstruct a typed ``Event`` from a stored row — everything a
    ``RunWindow`` needs, none of it lost by the store round trip."""
    envelope = {
        "schema": "trazo.v1",
        "event_id": row.event_id,
        "run_id": row.run_id,
        "project": run.project_id,
        "seq": row.seq,
        "ts": row.ts,
        "kind": row.kind,
        "payload": row.payload,
    }
    if row.step_id is not None:
        envelope["step_id"] = row.step_id
    if row.agent_id is not None:
        envelope["agent_id"] = row.agent_id
    if row.fingerprint is not None:
        envelope["fingerprint"] = row.fingerprint
    try:
        return EventAdapter.validate_python(envelope)
    except ValidationError:
        log.warning(
            "detector_worker.rebuild_skipped_invalid_row", event_id=row.event_id
        )
        return None


class DetectorWorker:
    """Drains ``EVENTS_STREAM`` under its own consumer group, maintaining
    one ``RunWindow`` per active run and dispatching every event to every
    configured ``Detector``."""

    def __init__(
        self,
        *,
        bus: EventBus,
        trace_store: TraceStore,
        detectors: list[Detector],
        consumer_name: str,
        on_detection: OnDetection = _log_detection,
        window_rebuild_size: int = 200,
        drift: DriftDetector | None = None,
    ) -> None:
        self._bus = bus
        self._trace_store = trace_store
        self._detectors = detectors
        self._consumer_name = consumer_name
        self._on_detection = on_detection
        self._window_rebuild_size = window_rebuild_size
        self._drift = drift
        self._windows: dict[str, RunWindow] = {}

    async def ensure_group(self) -> None:
        await self._bus.ensure_group(EVENTS_STREAM, DETECTOR_WORKER_GROUP)

    async def rebuild_running_windows(self) -> int:
        """Recovery path for a restart: replay every currently-``running``
        run's recent events through a fresh ``RunWindow`` so detector
        state picks up where it left off, without ever having persisted
        the window itself. Returns the count of runs rebuilt."""
        running = await self._trace_store.list_runs(status="running", limit=1000)
        for run in running:
            window = RunWindow(run.run_id)
            # Every event, a page at a time: the window's cost and token
            # totals are cumulative for the whole run, so reading only the
            # first page (as this once did) under-counted any longer run
            # and could hide a budget breach after a restart.
            position: tuple[int, int] | None = None
            while True:
                rows = await self._trace_store.get_events(
                    run.run_id,
                    after_seq=None if position is None else position[0],
                    after_sub_seq=None if position is None else position[1],
                    limit=self._window_rebuild_size,
                )
                for row in rows:
                    event = _event_row_to_event(run, row)
                    if event is not None:
                        window.record(event)
                if len(rows) < self._window_rebuild_size:
                    break
                position = (rows[-1].seq, rows[-1].sub_seq)
            self._windows[run.run_id] = window
        return len(running)

    async def poll_once(self, *, count: int = 100, block_ms: int = BUS_BLOCK_MS) -> int:
        messages = await self._bus.read_group(
            EVENTS_STREAM,
            DETECTOR_WORKER_GROUP,
            self._consumer_name,
            count=count,
            block_ms=block_ms,
        )
        await self._process_batch(messages)
        return len(messages)

    async def reclaim_once(self, *, min_idle_ms: int, count: int = 100) -> int:
        messages = await self._bus.reclaim_stale(
            EVENTS_STREAM,
            DETECTOR_WORKER_GROUP,
            self._consumer_name,
            min_idle_ms=min_idle_ms,
            count=count,
        )
        await self._process_batch(messages)
        return len(messages)

    async def run_forever(
        self,
        *,
        poll_block_ms: int = BUS_BLOCK_MS,
        reclaim_min_idle_ms: int = 30_000,
        reclaim_every: int = 10,
    ) -> None:
        """Never raises on a transient bus/store error — logs and keeps
        going, matching ``StoreWorker``'s own resilience contract (a
        worker that crashes the process on a momentary hiccup is worse
        than one briefly behind)."""
        iterations = 0
        started = False
        while True:
            try:
                if not started:
                    # Inside the loop, not a call before it: see
                    # StoreWorker.run_forever's identical guard — a
                    # Postgres/Redis hiccup at startup is transient, not
                    # fatal, and both ensure_group() and
                    # rebuild_running_windows() are safe to retry.
                    await self.ensure_group()
                    await self.rebuild_running_windows()
                    started = True
                await self.poll_once(block_ms=poll_block_ms)
                iterations += 1
                if iterations % reclaim_every == 0:
                    await self.reclaim_once(min_idle_ms=reclaim_min_idle_ms)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("detector_worker.iteration_failed")
                # redis-py's own internal async_timeout wraps a real
                # cancellation (from this task's own .cancel(), e.g. app
                # shutdown) delivered mid-poll into a plain
                # redis.exceptions.TimeoutError -- indistinguishable from
                # a genuine idle-poll timeout by type alone. Left
                # unchecked, that swallows the cancellation entirely: the
                # broad except below would just log and retry forever,
                # so whatever awaits this task (app.py's lifespan
                # shutdown) hangs until something else intervenes.
                # Task.cancelling() (3.11+) is how to tell the two apart.
                task = asyncio.current_task()
                if task is not None and task.cancelling() > 0:
                    raise asyncio.CancelledError() from None
                await asyncio.sleep(1)

    async def _process_batch(self, messages: list[BusMessage]) -> None:
        for message in messages:
            event = self._parse(message)
            if event is not None:
                await self._handle_event(event)
            await self._bus.ack(
                EVENTS_STREAM, DETECTOR_WORKER_GROUP, message.message_id
            )

    def _parse(self, message: BusMessage) -> Event | None:
        raw = message.fields.get("event")
        if raw is None:
            return None
        try:
            return EventAdapter.validate_json(raw)
        except ValidationError:
            log.warning("detector_worker.invalid_event", message_id=message.message_id)
            return None

    async def _handle_event(self, event: Event) -> None:
        window = self._windows.setdefault(event.run_id, RunWindow(event.run_id))
        window.record(event)

        for detector in self._detectors:
            detection = detector.on_event(event, window)
            if detection is not None:
                await self._on_detection(event, detection)

        if self._drift is not None:
            # A model call, run off the event loop; it fails open (a judge
            # that is down yields no detection, never an exception).
            detection = await self._drift.check(event, window)
            if detection is not None:
                await self._on_detection(event, detection)

        if event.kind == "run.finished":
            self._windows.pop(event.run_id, None)
            if self._drift is not None:
                self._drift.forget(event.run_id)
