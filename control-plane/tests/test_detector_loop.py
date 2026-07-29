"""Unit tests for LoopDetector (TRZ-P5-04), from synthetic streams."""

from __future__ import annotations

from typing import Any

from trazo_server.detectors.base import RunWindow
from trazo_server.detectors.loop import LoopDetector
from trazo_server.events import Event, EventAdapter

_RUN_ID = "run_1"


def _event(**overrides: Any) -> Event:
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
    return EventAdapter.validate_python(base)


def _tool_call(*, seq: int, fingerprint: str) -> Event:
    return _event(
        event_id=f"evt_{seq}",
        seq=seq,
        kind="tool.call",
        fingerprint=fingerprint,
        payload={
            "tool_name": "web_search",
            "args": {"query": "x"},
            "result": "y",
            "status": "ok",
            "latency_ms": 1.0,
            "side_effect_class": "external",
        },
    )


def _feed(detector: LoopDetector, window: RunWindow, events: list[Event]) -> list[Any]:
    detections = []
    for event in events:
        window.record(event)
        detection = detector.on_event(event, window)
        if detection is not None:
            detections.append(detection)
    return detections


def test_loop__fires_once_min_repeats_is_reached() -> None:
    detector = LoopDetector(min_repeats=5, window_events=20)
    window = RunWindow(_RUN_ID)
    fp = f"sha256:{'a' * 64}"
    events = [_tool_call(seq=i, fingerprint=fp) for i in range(5)]

    detections = _feed(detector, window, events)

    assert len(detections) == 1
    assert detections[0].detector == "loop"
    assert detections[0].details["repeat_count"] == 5


def test_loop__does_not_fire_below_min_repeats() -> None:
    detector = LoopDetector(min_repeats=5, window_events=20)
    window = RunWindow(_RUN_ID)
    fp = f"sha256:{'a' * 64}"
    events = [_tool_call(seq=i, fingerprint=fp) for i in range(4)]

    detections = _feed(detector, window, events)

    assert detections == []


def test_loop__distinct_fingerprints_never_fire() -> None:
    detector = LoopDetector(min_repeats=3, window_events=20)
    window = RunWindow(_RUN_ID)
    events = [_tool_call(seq=i, fingerprint=f"sha256:{str(i) * 64}") for i in range(10)]

    detections = _feed(detector, window, events)

    assert detections == []


def test_loop__repeats_outside_window_events_do_not_count() -> None:
    """A small window_events means only *recent* repeats count — an old
    repeat that's scrolled out of the window can't retroactively trigger."""
    detector = LoopDetector(min_repeats=3, window_events=3)
    window = RunWindow(_RUN_ID)
    fp = f"sha256:{'a' * 64}"
    # Two early repeats, then two distinct calls push them out of the
    # 3-event window before a third repeat of fp ever arrives.
    events = [
        _tool_call(seq=0, fingerprint=fp),
        _tool_call(seq=1, fingerprint=fp),
        _tool_call(seq=2, fingerprint=f"sha256:{'b' * 64}"),
        _tool_call(seq=3, fingerprint=f"sha256:{'c' * 64}"),
        _tool_call(seq=4, fingerprint=fp),  # 3rd fp repeat, but 0/1 are out of window
    ]

    detections = _feed(detector, window, events)

    assert detections == []


def test_loop__ignores_events_without_a_fingerprint() -> None:
    detector = LoopDetector(min_repeats=1, window_events=20)
    window = RunWindow(_RUN_ID)

    detections = _feed(detector, window, [_event(kind="run.started")])

    assert detections == []


def test_loop__thresholds_are_config_driven() -> None:
    lenient = LoopDetector(min_repeats=2, window_events=20)
    strict = LoopDetector(min_repeats=10, window_events=20)
    window_lenient = RunWindow(_RUN_ID)
    window_strict = RunWindow(_RUN_ID)
    fp = f"sha256:{'a' * 64}"
    events = [_tool_call(seq=i, fingerprint=fp) for i in range(3)]

    lenient_detections = _feed(lenient, window_lenient, events)
    strict_detections = _feed(strict, window_strict, events)

    assert len(lenient_detections) >= 1
    assert strict_detections == []
