"""Unit tests for ThrashDetector (TRZ-P5-04), from synthetic streams.

Ground-truth signature under test: cycling through a handful of distinct
tool-call fingerprints without ever turning up anything new — *not*
state-hash stagnation (see thrash.py's own docstring for why that
literal AI_DEBUGGER.md §1 wording was dropped)."""

from __future__ import annotations

from typing import Any

from trazo_server.detectors.base import RunWindow
from trazo_server.detectors.thrash import ThrashDetector
from trazo_server.events import Event, EventAdapter

_RUN_ID = "run_1"


def _tool_call(
    *,
    seq: int,
    fingerprint: str,
    tool_name: str = "web_search",
    result: Any = "no results",
) -> Event:
    base: dict[str, Any] = {
        "schema": "trazo.v1",
        "event_id": f"evt_tool_{seq}",
        "run_id": _RUN_ID,
        "project": "proj",
        "seq": seq,
        "ts": "2026-07-18T09:30:00.000Z",
        "kind": "tool.call",
        "fingerprint": fingerprint,
        "payload": {
            "tool_name": tool_name,
            "args": {},
            "result": result,
            "status": "ok",
            "latency_ms": 1.0,
            "side_effect_class": "external",
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


_FP_A = f"sha256:{'a' * 64}"
_FP_B = f"sha256:{'b' * 64}"
_FP_C = f"sha256:{'c' * 64}"


def test_thrash__fires_when_cycling_through_a_fixed_set_of_fingerprints() -> None:
    """3 distinct fingerprints (queries), all seen once already, then
    the window's second half repeats only fingerprints from the first
    half -- nothing new discovered."""
    detector = ThrashDetector(min_distinct_calls=2, window_calls=6)
    window = RunWindow(_RUN_ID)
    events = [
        _tool_call(seq=0, fingerprint=_FP_A),
        _tool_call(seq=1, fingerprint=_FP_B),
        _tool_call(seq=2, fingerprint=_FP_C),
        _tool_call(seq=3, fingerprint=_FP_A),
        _tool_call(seq=4, fingerprint=_FP_B),
        _tool_call(seq=5, fingerprint=_FP_C),
    ]

    detections = _feed(detector, window, events)

    assert len(detections) == 1
    assert detections[0].detector == "thrash"
    assert detections[0].details["distinct_fingerprint_count"] == 3


def test_thrash__does_not_fire_when_a_new_fingerprint_keeps_appearing() -> None:
    """Every call turns up something the window hasn't seen before --
    real progress, not thrash."""
    detector = ThrashDetector(min_distinct_calls=2, window_calls=6)
    window = RunWindow(_RUN_ID)
    events = [
        _tool_call(seq=i, fingerprint=f"sha256:{chr(97 + i) * 64}") for i in range(6)
    ]

    detections = _feed(detector, window, events)

    assert detections == []


def test_thrash__does_not_fire_when_one_fingerprint_dominates() -> None:
    """A single stale one-off plus five repeats of the same exact call is
    an exact-repeat loop wearing a Thrash costume -- LoopDetector's
    signature, not this one's."""
    detector = ThrashDetector(min_distinct_calls=2, window_calls=6)
    window = RunWindow(_RUN_ID)
    events = [
        _tool_call(seq=0, fingerprint=_FP_B, tool_name="fetch_document"),
        _tool_call(seq=1, fingerprint=_FP_A),
        _tool_call(seq=2, fingerprint=_FP_A),
        _tool_call(seq=3, fingerprint=_FP_A),
        _tool_call(seq=4, fingerprint=_FP_A),
        _tool_call(seq=5, fingerprint=_FP_A),
    ]

    detections = _feed(detector, window, events)

    assert detections == []


def test_thrash__does_not_fire_below_min_distinct_calls() -> None:
    """Only one fingerprint ever appears -- that's LoopDetector's exact-
    repeat territory, not Thrash's cycling-repertoire signature."""
    detector = ThrashDetector(min_distinct_calls=2, window_calls=6)
    window = RunWindow(_RUN_ID)
    events = [_tool_call(seq=i, fingerprint=_FP_A) for i in range(6)]

    detections = _feed(detector, window, events)

    assert detections == []


def test_thrash__needs_the_full_window_before_judging() -> None:
    detector = ThrashDetector(min_distinct_calls=2, window_calls=10)
    window = RunWindow(_RUN_ID)
    events = [
        _tool_call(seq=0, fingerprint=_FP_A),
        _tool_call(seq=1, fingerprint=_FP_B),
        _tool_call(seq=2, fingerprint=_FP_A),
        _tool_call(seq=3, fingerprint=_FP_B),
    ]  # only 4 calls, window_calls=10 needs 10

    detections = _feed(detector, window, events)

    assert detections == []


def test_thrash__non_tool_call_events_never_trigger_the_check() -> None:
    detector = ThrashDetector(min_distinct_calls=1, window_calls=1)
    window = RunWindow(_RUN_ID)

    base: dict[str, Any] = {
        "schema": "trazo.v1",
        "event_id": "evt_step_0",
        "run_id": _RUN_ID,
        "project": "proj",
        "seq": 0,
        "ts": "2026-07-18T09:30:00.000Z",
        "kind": "step.finished",
        "payload": {
            "status": "ok",
            "state_after_hash": f"sha256:{'1' * 64}",
            "state_after": {},
            "duration_ms": 1.0,
        },
    }
    event = EventAdapter.validate_python(base)
    window.record(event)
    detection = detector.on_event(event, window)

    assert detection is None


def test_thrash__does_not_fire_when_different_calls_return_different_results() -> None:
    """The same three queries cycle, but each returns its own answer: the
    agent is revisiting calls and still learning from them -- a healthy
    retry pattern, not thrash. This is the shape that made every long
    benchmark run (budget and drift ones included) look like thrash when
    only the calls were compared."""
    detector = ThrashDetector(min_distinct_calls=2, window_calls=6)
    window = RunWindow(_RUN_ID)
    fingerprints = [_FP_A, _FP_B, _FP_C, _FP_A, _FP_B, _FP_C]
    events = [
        _tool_call(seq=i, fingerprint=fp, result=f"answer for {fp[-4:]}")
        for i, fp in enumerate(fingerprints)
    ]

    assert _feed(detector, window, events) == []


def test_thrash__fires_when_one_result_comes_back_for_every_call() -> None:
    detector = ThrashDetector(min_distinct_calls=2, window_calls=6)
    window = RunWindow(_RUN_ID)
    fingerprints = [_FP_A, _FP_B, _FP_C, _FP_A, _FP_B, _FP_C]
    events = [
        _tool_call(seq=i, fingerprint=fp, result={"hits": []})
        for i, fp in enumerate(fingerprints)
    ]

    detections = _feed(detector, window, events)

    assert len(detections) == 1
    assert detections[0].details["distinct_result_count"] == 1


def test_thrash__one_differing_result_in_the_window_is_enough_to_stay_quiet() -> None:
    detector = ThrashDetector(min_distinct_calls=2, window_calls=6)
    window = RunWindow(_RUN_ID)
    fingerprints = [_FP_A, _FP_B, _FP_C, _FP_A, _FP_B, _FP_C]
    events = [
        _tool_call(seq=i, fingerprint=fp, result="no results" if i else "found it")
        for i, fp in enumerate(fingerprints)
    ]

    assert _feed(detector, window, events) == []
