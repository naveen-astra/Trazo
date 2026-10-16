"""Persists a Detection as a real ``detection.raised`` event (TRZ-P5-06).

Replaces ``DetectorWorker``'s default ``on_detection`` (a structured-
log-only stub, TRZ-P5-03) with the real path: record the event through
``TraceStore.append_server_event``, attached after the event that
triggered it, then republish it onto ``EVENTS_STREAM`` so ``StoreWorker``
maintains the ``detections`` projection table and any live SSE/dashboard
subscriber sees the detection the moment it is raised.

Safe to retry, and it does retry: a detection is keyed on (triggering
event, detector), and detectors are pure functions of the window, so the
same trigger can only ever produce the same detection. A transient
failure (a database deadlock, a dropped connection) is retried here, in
place, rather than left to the bus's reclaim. Reclaim redelivers the
event tens of seconds later, by which time a short run has finished and
its in-memory window is gone, so the detection would never fire again --
which is exactly how one was lost on 2026-10-16.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

import structlog

from trazo_server.bus.protocol import EventBus
from trazo_server.detectors.base import Detection
from trazo_server.events import Event, EventAdapter
from trazo_server.store.trace_store import TraceStore
from trazo_server.topics import EVENTS_STREAM
from trazo_server.ulid import new_event_id

log = structlog.get_logger(__name__)

# Five attempts over roughly 1.5 seconds: long enough to outlast a
# deadlock victim's rollback or a brief Postgres/Redis restart, short
# enough not to stall the detector worker's consumer.
_RETRY_DELAYS_SECONDS: tuple[float, ...] = (0.05, 0.15, 0.4, 0.9)


def idempotency_key(event: Event, detection: Detection) -> str:
    return f"detection:{event.event_id}:{detection.detector}"


class PersistDetection:
    """Callable matching ``DetectorWorker``'s ``OnDetection`` signature."""

    def __init__(
        self,
        *,
        trace_store: TraceStore,
        bus: EventBus,
        retry_delays: tuple[float, ...] = _RETRY_DELAYS_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._trace_store = trace_store
        self._bus = bus
        self._retry_delays = retry_delays
        self._sleep = sleep

    async def __call__(self, event: Event, detection: Detection) -> None:
        for delay in (*self._retry_delays, None):
            try:
                await self._persist(event, detection)
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                if delay is None:
                    raise
                log.warning(
                    "detection_persistence.retrying",
                    run_id=event.run_id,
                    detector=detection.detector,
                    retry_in_seconds=delay,
                    exc_info=True,
                )
                await self._sleep(delay)

    async def _persist(self, event: Event, detection: Detection) -> None:
        payload = {
            "detector": detection.detector,
            "severity": detection.severity,
            "evidence_event_ids": detection.evidence_event_ids,
            "details": detection.details,
            "window": detection.window,
        }
        ts = datetime.now(timezone.utc)
        appended = await self._trace_store.append_server_event(
            run_id=event.run_id,
            project=event.project,
            after_seq=event.seq,
            # Minted now, not derived from the trigger: the firehose pages
            # on event_id, so an id that sorted near the (already streamed)
            # trigger would fall behind subscribers' cursors and never be
            # delivered live. A retry reuses the first attempt's id via the
            # idempotency key.
            event_id=new_event_id(),
            kind="detection.raised",
            ts=ts,
            payload=payload,
            idempotency_key=idempotency_key(event, detection),
        )

        envelope = EventAdapter.validate_python(
            {
                "schema": "trazo.v1",
                "event_id": appended.event_id,
                "run_id": event.run_id,
                "project": event.project,
                "seq": appended.seq,
                "ts": ts.isoformat(),
                "kind": "detection.raised",
                "payload": payload,
            }
        )
        encoded = EventAdapter.dump_json(envelope, by_alias=True, exclude_none=True)
        # Republished even when the row already existed: the earlier attempt
        # may have failed between writing it and publishing it, and the
        # store worker's projection insert is idempotent on event_id.
        await self._bus.publish(EVENTS_STREAM, {"event": encoded.decode("utf-8")})
