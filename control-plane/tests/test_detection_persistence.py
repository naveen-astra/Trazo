"""Unit tests for PersistDetection (TRZ-P5-06)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest

from trazo_server.bus.memory import InMemoryEventBus
from trazo_server.detectors.base import Detection
from trazo_server.events import Event, EventAdapter
from trazo_server.store.memory_trace_store import InMemoryTraceStore
from trazo_server.store.rows import AppendedEvent
from trazo_server.topics import EVENTS_STREAM
from trazo_server.workers.detection_persistence import PersistDetection

_RUN_ID = "run_1"


def _triggering_event(*, seq: int = 7, event_id: str = "evt_trigger") -> Event:
    base: dict[str, Any] = {
        "schema": "trazo.v1",
        "event_id": event_id,
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


def _detection(detector: str = "loop") -> Detection:
    return Detection(
        detector=detector,
        severity="warn",
        evidence_event_ids=["evt_a", "evt_b"],
        details={"repeat_count": 4},
        window={"step_count": 10},
    )


async def _no_sleep(_seconds: float) -> None:
    return None


async def _published(bus: InMemoryEventBus) -> list[dict[str, Any]]:
    await bus.ensure_group(EVENTS_STREAM, "test-reader")
    messages = await bus.read_group(
        EVENTS_STREAM, "test-reader", "consumer-1", count=100, block_ms=0
    )
    return [json.loads(m.fields["event"]) for m in messages]


async def test_persist_detection__attaches_right_after_the_triggering_event() -> None:
    trace_store = InMemoryTraceStore()
    persist = PersistDetection(trace_store=trace_store, bus=InMemoryEventBus())

    await persist(_triggering_event(seq=7), _detection())

    [inserted] = await trace_store.get_server_events(_RUN_ID)
    assert (inserted.seq, inserted.sub_seq) == (7, 1)
    assert inserted.kind == "detection.raised"
    assert inserted.payload["detector"] == "loop"
    assert inserted.payload["evidence_event_ids"] == ["evt_a", "evt_b"]


async def test_persist_detection__republishes_onto_events_stream() -> None:
    trace_store = InMemoryTraceStore()
    bus = InMemoryEventBus()
    persist = PersistDetection(trace_store=trace_store, bus=bus)

    await persist(_triggering_event(seq=7), _detection())

    [published] = await _published(bus)
    assert published["kind"] == "detection.raised"
    assert published["run_id"] == _RUN_ID
    assert published["seq"] == 7
    assert published["payload"]["detector"] == "loop"


async def test_persist_detection__the_same_trigger_and_detector_is_recorded_once() -> (
    None
):
    """Detectors are pure, so a redelivered trigger yields the same
    detection; recording it twice would double-count the incident."""
    trace_store = InMemoryTraceStore()
    persist = PersistDetection(trace_store=trace_store, bus=InMemoryEventBus())

    await persist(_triggering_event(), _detection())
    await persist(_triggering_event(), _detection())

    assert len(await trace_store.get_server_events(_RUN_ID)) == 1


async def test_persist_detection__different_detectors_on_one_trigger_both_land() -> (
    None
):
    trace_store = InMemoryTraceStore()
    persist = PersistDetection(trace_store=trace_store, bus=InMemoryEventBus())

    await persist(_triggering_event(), _detection("loop"))
    await persist(_triggering_event(), _detection("thrash"))

    rows = await trace_store.get_server_events(_RUN_ID)
    assert [(r.seq, r.sub_seq, r.payload["detector"]) for r in rows] == [
        (7, 1, "loop"),
        (7, 2, "thrash"),
    ]


class _FlakyStore(InMemoryTraceStore):
    """Fails the first ``failures`` appends, the way a deadlock victim or a
    dropped connection does."""

    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures
        self.calls = 0

    async def append_server_event(self, **kwargs: Any) -> AppendedEvent:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("deadlock detected")
        return await super().append_server_event(**kwargs)


async def test_persist_detection__retries_a_transient_failure_in_place() -> None:
    """Regression for the detection lost on 2026-10-16: a deadlock failed
    the write, and the event was only retried by the bus's reclaim, ~45s
    later, after the run had finished and its window was gone."""
    trace_store = _FlakyStore(failures=2)
    bus = InMemoryEventBus()
    persist = PersistDetection(trace_store=trace_store, bus=bus, sleep=_no_sleep)

    await persist(_triggering_event(), _detection())

    assert trace_store.calls == 3
    assert len(await trace_store.get_server_events(_RUN_ID)) == 1
    assert len(await _published(bus)) == 1


async def test_persist_detection__raises_once_retries_are_exhausted() -> None:
    trace_store = _FlakyStore(failures=99)
    persist = PersistDetection(
        trace_store=trace_store,
        bus=InMemoryEventBus(),
        retry_delays=(0.0, 0.0),
        sleep=_no_sleep,
    )

    with pytest.raises(RuntimeError, match="deadlock"):
        await persist(_triggering_event(), _detection())

    assert trace_store.calls == 3  # first attempt + one per retry delay


class _FlakyBus(InMemoryEventBus):
    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures

    async def publish(self, stream: str, fields: Mapping[str, str]) -> str:
        if self.failures > 0:
            self.failures -= 1
            raise ConnectionError("redis unavailable")
        return await super().publish(stream, fields)


async def test_persist_detection__retry_after_a_commit_does_not_duplicate() -> None:
    """The write committed but the publish failed: the retry must find its
    own earlier row, not record a second detection."""
    trace_store = InMemoryTraceStore()
    bus = _FlakyBus(failures=1)
    persist = PersistDetection(trace_store=trace_store, bus=bus, sleep=_no_sleep)

    await persist(_triggering_event(), _detection())

    rows = await trace_store.get_server_events(_RUN_ID)
    assert len(rows) == 1
    [published] = await _published(bus)
    assert published["event_id"] == rows[0].event_id
