"""Unit tests for DetectorWorker (TRZ-P5-03).

DoD: a restart-rebuild test proving RunWindow state (never itself
persisted) is correctly reconstructed from TraceStore for any run still
"running" when the worker (re)starts — the recovery path after a crash.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from trazo_server.bus.memory import InMemoryEventBus
from trazo_server.bus.protocol import EventBus
from trazo_server.detectors.base import Detection, RunWindow
from trazo_server.events import Event
from trazo_server.store.memory_trace_store import InMemoryTraceStore
from trazo_server.store.rows import EventRow, RunRow
from trazo_server.topics import EVENTS_STREAM
from trazo_server.workers.detector_worker import DetectorWorker

_NOW = datetime(2026, 7, 18, 9, 30, tzinfo=timezone.utc)
_RUN_ID = "run_1"


def _event(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema": "trazo.v1",
        "event_id": "evt_1",
        "run_id": _RUN_ID,
        "project": "proj",
        "seq": 0,
        "ts": "2026-07-18T09:30:00.000Z",
        "kind": "run.started",
        "payload": {
            "framework": "langgraph",
            "framework_version": "0.2.39",
            "sdk_version": "0.1.0",
            "entry_input": {},
            "tags": {},
        },
    }
    base.update(overrides)
    return base


def _llm_call_event(*, event_id: str, seq: int, cost_usd: float) -> dict[str, Any]:
    return _event(
        event_id=event_id,
        seq=seq,
        kind="llm.call",
        fingerprint=f"sha256:{'a' * 64}",
        payload={
            "provider": "fixture",
            "model": "fixture-v1",
            "params": {},
            "messages_in": {},
            "response": "hi",
            "tokens_in": 10,
            "tokens_out": 5,
            "cost_usd": cost_usd,
            "latency_ms": 1.0,
        },
    )


async def _publish(bus: EventBus, *events: dict[str, Any]) -> None:
    for event in events:
        await bus.publish(EVENTS_STREAM, {"event": json.dumps(event)})


class _RecordingDetector:
    """A detector that just remembers every window it was shown, so tests
    can assert on accumulated state without needing a real threshold rule."""

    id = "recording"

    def __init__(self) -> None:
        self.seen_totals: list[float] = []

    def on_event(self, event: Event, window: RunWindow) -> Detection | None:
        self.seen_totals.append(window.cost_usd_total)
        return None


async def test_detector_worker__dispatches_events_to_every_detector() -> None:
    bus = InMemoryEventBus()
    trace_store = InMemoryTraceStore()
    detector = _RecordingDetector()
    worker = DetectorWorker(
        bus=bus, trace_store=trace_store, detectors=[detector], consumer_name="w1"
    )
    await worker.ensure_group()

    await _publish(
        bus,
        _event(),
        _llm_call_event(event_id="evt_llm_1", seq=1, cost_usd=1.5),
    )
    await worker.poll_once(count=10, block_ms=0)

    assert detector.seen_totals == [0.0, 1.5]


async def test_detector_worker__frees_the_window_on_run_finished() -> None:
    bus = InMemoryEventBus()
    trace_store = InMemoryTraceStore()
    detector = _RecordingDetector()
    worker = DetectorWorker(
        bus=bus, trace_store=trace_store, detectors=[detector], consumer_name="w1"
    )
    await worker.ensure_group()

    await _publish(bus, _event())
    await worker.poll_once(count=10, block_ms=0)
    assert _RUN_ID in worker._windows

    await _publish(
        bus,
        _event(
            event_id="evt_finished",
            seq=1,
            kind="run.finished",
            payload={
                "status": "ok",
                "totals": {
                    "events": 2,
                    "llm_calls": 0,
                    "tool_calls": 0,
                    "cost_usd": 0.0,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "duration_ms": 1.0,
                },
            },
        ),
    )
    await worker.poll_once(count=10, block_ms=0)

    assert _RUN_ID not in worker._windows


async def test_detector_worker__custom_on_detection_callback_is_invoked() -> None:
    bus = InMemoryEventBus()
    trace_store = InMemoryTraceStore()

    class _AlwaysDetects:
        id = "always"

        def on_event(self, event: Event, window: RunWindow) -> Detection | None:
            return Detection(
                detector="loop",
                severity="warn",
                evidence_event_ids=[event.event_id],
                details={},
                window=window.as_summary(),
            )

    seen: list[Detection] = []

    async def _capture(event: Event, detection: Detection) -> None:
        seen.append(detection)

    worker = DetectorWorker(
        bus=bus,
        trace_store=trace_store,
        detectors=[_AlwaysDetects()],
        consumer_name="w1",
        on_detection=_capture,
    )
    await worker.ensure_group()

    await _publish(bus, _event())
    await worker.poll_once(count=10, block_ms=0)

    assert len(seen) == 1
    assert seen[0].detector == "loop"


async def test_detector_worker__restart_rebuild_recovers_window_state_from_store() -> (
    None
):
    """The DoD: a worker started fresh (as after a crash/restart) must
    reconstruct a running run's window from TraceStore alone — no bus
    replay needed — so a detector immediately sees the *full*
    accumulated history, not just events arriving after the restart."""
    trace_store = InMemoryTraceStore()
    await trace_store.ensure_project("proj_1", "proj")
    await trace_store.upsert_run(
        RunRow(
            run_id=_RUN_ID,
            project_id="proj_1",
            framework="langgraph",
            status="running",
            started_at=_NOW,
            finished_at=None,
            tags={},
            totals={},
        )
    )
    await trace_store.upsert_events(
        [
            EventRow(
                run_id=_RUN_ID,
                seq=0,
                event_id="evt_0",
                kind="run.started",
                ts=_NOW,
                step_id=None,
                agent_id=None,
                fingerprint=None,
                payload={
                    "framework": "langgraph",
                    "framework_version": "0.2.39",
                    "sdk_version": "0.1.0",
                    "entry_input": {},
                    "tags": {},
                },
                blobs=[],
            ),
            EventRow(
                run_id=_RUN_ID,
                seq=1,
                event_id="evt_1",
                kind="llm.call",
                ts=_NOW,
                step_id=None,
                agent_id=None,
                fingerprint=f"sha256:{'a' * 64}",
                payload={
                    "provider": "fixture",
                    "model": "fixture-v1",
                    "params": {},
                    "messages_in": {},
                    "response": "hi",
                    "tokens_in": 10,
                    "tokens_out": 5,
                    "cost_usd": 2.5,
                    "latency_ms": 1.0,
                },
                blobs=[],
            ),
        ]
    )

    # A brand-new worker — as if the process just (re)started, with
    # nothing in memory yet.
    bus = InMemoryEventBus()
    detector = _RecordingDetector()
    worker = DetectorWorker(
        bus=bus, trace_store=trace_store, detectors=[detector], consumer_name="w1"
    )

    rebuilt_count = await worker.rebuild_running_windows()

    assert rebuilt_count == 1
    assert worker._windows[_RUN_ID].cost_usd_total == 2.5
    assert worker._windows[_RUN_ID].step_count == 0

    # A brand-new event arrives after the restart — the detector must see
    # the *rebuilt* total (2.5) plus this new call's cost, not start over.
    await worker.ensure_group()
    await _publish(bus, _llm_call_event(event_id="evt_2", seq=2, cost_usd=1.0))
    await worker.poll_once(count=10, block_ms=0)

    assert detector.seen_totals == [3.5]
