"""Persists a Detection as a real ``detection.raised`` event (TRZ-P5-06).

Replaces ``DetectorWorker``'s default ``on_detection`` (a structured-
log-only stub, TRZ-P5-03) with the real path: mint a seq via
``TraceStore.append_event`` (the store-side reservation that method's
own docstring explains is required — a detection is discovered
server-side, with no access to the SDK's per-run seq counter), then
republish the resulting event onto ``EVENTS_STREAM`` so ``StoreWorker``'s
existing generic consumption maintains the ``detections`` projection
table (its own new branch, mirroring how it already handles
``run.started``/``run.finished``) and any live SSE/dashboard subscriber
sees the detection the moment it's raised.
"""

from __future__ import annotations

from datetime import datetime, timezone

from trazo_server.bus.protocol import EventBus
from trazo_server.detectors.base import Detection
from trazo_server.events import Event, EventAdapter
from trazo_server.store.trace_store import TraceStore
from trazo_server.topics import EVENTS_STREAM
from trazo_server.ulid import new_event_id


class PersistDetection:
    """Callable matching ``DetectorWorker``'s ``OnDetection`` signature."""

    def __init__(self, *, trace_store: TraceStore, bus: EventBus) -> None:
        self._trace_store = trace_store
        self._bus = bus

    async def __call__(self, event: Event, detection: Detection) -> None:
        payload = {
            "detector": detection.detector,
            "severity": detection.severity,
            "evidence_event_ids": detection.evidence_event_ids,
            "details": detection.details,
            "window": detection.window,
        }
        event_id = new_event_id()
        ts = datetime.now(timezone.utc)
        seq = await self._trace_store.append_event(
            run_id=event.run_id,
            event_id=event_id,
            kind="detection.raised",
            ts=ts,
            fingerprint=None,
            payload=payload,
        )

        envelope = EventAdapter.validate_python(
            {
                "schema": "trazo.v1",
                "event_id": event_id,
                "run_id": event.run_id,
                "project": event.project,
                "seq": seq,
                "ts": ts.isoformat(),
                "kind": "detection.raised",
                "payload": payload,
            }
        )
        encoded = EventAdapter.dump_json(envelope, by_alias=True, exclude_none=True)
        await self._bus.publish(EVENTS_STREAM, {"event": encoded.decode("utf-8")})
