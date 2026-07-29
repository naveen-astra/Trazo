"""Unit tests for PersistDetection (TRZ-P5-06)."""

from __future__ import annotations

import json
from typing import Any

from trazo_server.bus.memory import InMemoryEventBus
from trazo_server.detectors.base import Detection
from trazo_server.events import Event, EventAdapter
from trazo_server.store.memory_trace_store import InMemoryTraceStore
from trazo_server.topics import EVENTS_STREAM
from trazo_server.workers.detection_persistence import PersistDetection

_RUN_ID = "run_1"


def _triggering_event(*, seq: int = 7) -> Event:
    base: dict[str, Any] = {
        "schema": "trazo.v1",
        "event_id": "evt_trigger",
        "run_id": _RUN_ID,
        "project": "research-assistant",
        "seq": seq,
        "ts": "2026-07-18T09:30:00.000Z",
        "kind": "tool.call",
        "fingerprint": f"sha256:{'a' * 64}",
        "payload": {
            "tool_name": "web_search",
            "args": {},
            "result": "no results",
            "status": "ok",
            "latency_ms": 1.0,
            "side_effect_class": "external",
        },
    }
    return EventAdapter.validate_python(base)


def _detection() -> Detection:
    return Detection(
        detector="loop",
        severity="warn",
        evidence_event_ids=["evt_a", "evt_b"],
        details={"repeat_count": 4},
        window={"step_count": 10},
    )


async def test_persist_detection__inserts_a_detection_raised_event_row() -> None:
    trace_store = InMemoryTraceStore()
    bus = InMemoryEventBus()
    persist = PersistDetection(trace_store=trace_store, bus=bus)

    await persist(_triggering_event(seq=7), _detection())

    events = await trace_store.get_events(_RUN_ID)
    [inserted] = [e for e in events if e.kind == "detection.raised"]
    assert inserted.seq == 0  # no prior events for this run in the fake store
    assert inserted.payload["detector"] == "loop"
    assert inserted.payload["evidence_event_ids"] == ["evt_a", "evt_b"]


async def test_persist_detection__republishes_onto_events_stream() -> None:
    trace_store = InMemoryTraceStore()
    bus = InMemoryEventBus()
    persist = PersistDetection(trace_store=trace_store, bus=bus)

    await persist(_triggering_event(), _detection())

    await bus.ensure_group(EVENTS_STREAM, "test-reader")
    [message] = await bus.read_group(
        EVENTS_STREAM, "test-reader", "consumer-1", count=10, block_ms=0
    )
    published = json.loads(message.fields["event"])
    assert published["kind"] == "detection.raised"
    assert published["run_id"] == _RUN_ID
    assert published["payload"]["detector"] == "loop"


async def test_persist_detection__second_detection_on_same_run_gets_next_seq() -> None:
    trace_store = InMemoryTraceStore()
    bus = InMemoryEventBus()
    persist = PersistDetection(trace_store=trace_store, bus=bus)

    await persist(_triggering_event(), _detection())
    await persist(_triggering_event(), _detection())

    events = await trace_store.get_events(_RUN_ID)
    raised = [e for e in events if e.kind == "detection.raised"]
    assert [e.seq for e in raised] == [0, 1]
