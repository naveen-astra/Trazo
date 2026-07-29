"""Unit tests for ThrashDetector (TRZ-P5-04), from synthetic streams."""

from __future__ import annotations

from typing import Any

from trazo_server.detectors.base import RunWindow
from trazo_server.detectors.thrash import ThrashDetector
from trazo_server.events import Event, EventAdapter

_RUN_ID = "run_1"


def _tool_call(*, seq: int, tool_name: str) -> Event:
    base: dict[str, Any] = {
        "schema": "trazo.v1",
        "event_id": f"evt_tool_{seq}",
        "run_id": _RUN_ID,
        "project": "proj",
        "seq": seq,
        "ts": "2026-07-18T09:30:00.000Z",
        "kind": "tool.call",
        "fingerprint": f"sha256:{'a' * 64}",
        "payload": {
            "tool_name": tool_name,
            "args": {},
            "result": "no results",
            "status": "ok",
            "latency_ms": 1.0,
            "side_effect_class": "external",
        },
    }
    return EventAdapter.validate_python(base)


def _step_finished(*, seq: int, state_after_hash: str) -> Event:
    base: dict[str, Any] = {
        "schema": "trazo.v1",
        "event_id": f"evt_step_{seq}",
        "run_id": _RUN_ID,
        "project": "proj",
        "seq": seq,
        "ts": "2026-07-18T09:30:00.000Z",
        "kind": "step.finished",
        "payload": {
            "status": "ok",
            "state_after_hash": state_after_hash,
            "state_after": {},
            "duration_ms": 1.0,
        },
    }
    return EventAdapter.validate_python(base)


def _feed(
    detector: ThrashDetector, window: RunWindow, events: list[Event]
) -> list[Any]:
    detections = []
    for event in events:
        window.record(event)
        detection = detector.on_event(event, window)
        if detection is not None:
            detections.append(detection)
    return detections


_STUCK_HASH = f"sha256:{'1' * 64}"


def test_thrash__fires_with_diverse_tools_and_unchanged_state() -> None:
    """The detector only evaluates *on* tool.call events, so the stream
    needs one more tool.call after the step_window's worth of
    step.finished events has actually accumulated."""
    detector = ThrashDetector(min_distinct_tools=2, step_window=3)
    window = RunWindow(_RUN_ID)
    events = [
        _step_finished(seq=0, state_after_hash=_STUCK_HASH),
        _tool_call(seq=1, tool_name="web_search"),
        _step_finished(seq=2, state_after_hash=_STUCK_HASH),
        _tool_call(seq=3, tool_name="fetch_document"),
        _step_finished(seq=4, state_after_hash=_STUCK_HASH),
        _tool_call(seq=5, tool_name="web_search"),
    ]

    detections = _feed(detector, window, events)

    assert len(detections) >= 1
    assert detections[0].detector == "thrash"
    assert set(detections[0].details["distinct_tools"]) == {
        "web_search",
        "fetch_document",
    }


def test_thrash__does_not_fire_when_state_actually_changes() -> None:
    detector = ThrashDetector(min_distinct_tools=2, step_window=3)
    window = RunWindow(_RUN_ID)
    events = [
        _step_finished(seq=0, state_after_hash=f"sha256:{'1' * 64}"),
        _tool_call(seq=1, tool_name="web_search"),
        _step_finished(seq=2, state_after_hash=f"sha256:{'2' * 64}"),  # progress!
        _tool_call(seq=3, tool_name="fetch_document"),
        _step_finished(seq=4, state_after_hash=f"sha256:{'3' * 64}"),  # still changing
        _tool_call(seq=5, tool_name="web_search"),
    ]

    detections = _feed(detector, window, events)

    assert detections == []


def test_thrash__does_not_fire_below_min_distinct_tools() -> None:
    detector = ThrashDetector(min_distinct_tools=3, step_window=2)
    window = RunWindow(_RUN_ID)
    events = [
        _step_finished(seq=0, state_after_hash=_STUCK_HASH),
        _tool_call(seq=1, tool_name="web_search"),
        _step_finished(seq=2, state_after_hash=_STUCK_HASH),
        _tool_call(seq=3, tool_name="web_search"),  # same tool every time
        _step_finished(seq=4, state_after_hash=_STUCK_HASH),
    ]

    detections = _feed(detector, window, events)

    assert detections == []


def test_thrash__needs_the_full_step_window_before_judging() -> None:
    detector = ThrashDetector(min_distinct_tools=2, step_window=10)
    window = RunWindow(_RUN_ID)
    events = [
        _step_finished(seq=0, state_after_hash=_STUCK_HASH),
        _tool_call(seq=1, tool_name="web_search"),
        _step_finished(seq=2, state_after_hash=_STUCK_HASH),
        _tool_call(seq=3, tool_name="fetch_document"),
    ]  # only 2 step.finished events, step_window=10 needs 10

    detections = _feed(detector, window, events)

    assert detections == []


def test_thrash__non_tool_call_events_never_trigger_the_check() -> None:
    detector = ThrashDetector(min_distinct_tools=1, step_window=1)
    window = RunWindow(_RUN_ID)

    detection = None
    event = _step_finished(seq=0, state_after_hash=_STUCK_HASH)
    window.record(event)
    detection = detector.on_event(event, window)

    assert detection is None
