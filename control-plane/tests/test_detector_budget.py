"""Unit tests for BudgetDetector (TRZ-P5-04), from synthetic streams."""

from __future__ import annotations

from typing import Any

from trazo_server.detectors.base import RunWindow
from trazo_server.detectors.budget import BudgetDetector
from trazo_server.events import Event, EventAdapter

_RUN_ID = "run_1"


def _llm_call(
    *, seq: int, cost_usd: float, tokens_in: int = 1, tokens_out: int = 1
) -> Event:
    base: dict[str, Any] = {
        "schema": "trazo.v1",
        "event_id": f"evt_{seq}",
        "run_id": _RUN_ID,
        "project": "proj",
        "seq": seq,
        "ts": "2026-07-18T09:30:00.000Z",
        "kind": "llm.call",
        "fingerprint": f"sha256:{'a' * 64}",
        "payload": {
            "provider": "fixture",
            "model": "fixture-v1",
            "params": {},
            "messages_in": {},
            "response": "hi",
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
            "latency_ms": 1.0,
        },
    }
    return EventAdapter.validate_python(base)


def _feed(
    detector: BudgetDetector, window: RunWindow, events: list[Event]
) -> list[Any]:
    detections = []
    for event in events:
        window.record(event)
        detection = detector.on_event(event, window)
        if detection is not None:
            detections.append(detection)
    return detections


def test_budget__absolute_cost_ceiling_fires() -> None:
    detector = BudgetDetector(max_cost_usd=1.0, max_tokens=1_000_000)
    window = RunWindow(_RUN_ID)
    events = [_llm_call(seq=0, cost_usd=0.5), _llm_call(seq=1, cost_usd=0.6)]

    detections = _feed(detector, window, events)

    assert len(detections) == 1
    assert detections[0].details["reason"] == "absolute_budget_exceeded"


def test_budget__under_ceiling_does_not_fire() -> None:
    detector = BudgetDetector(
        max_cost_usd=10.0, max_tokens=1_000_000, velocity_multiplier=100.0
    )
    window = RunWindow(_RUN_ID)
    events = [_llm_call(seq=0, cost_usd=0.1), _llm_call(seq=1, cost_usd=0.1)]

    detections = _feed(detector, window, events)

    assert detections == []


def test_budget__absolute_token_ceiling_fires() -> None:
    detector = BudgetDetector(max_cost_usd=1_000_000.0, max_tokens=100)
    window = RunWindow(_RUN_ID)
    events = [_llm_call(seq=0, cost_usd=0.0, tokens_in=60, tokens_out=60)]

    detections = _feed(detector, window, events)

    assert len(detections) == 1
    assert detections[0].details["reason"] == "absolute_budget_exceeded"


def test_budget__velocity_spike_fires_before_absolute_ceiling() -> None:
    detector = BudgetDetector(
        max_cost_usd=1_000_000.0,  # so only velocity can fire
        max_tokens=1_000_000,
        velocity_multiplier=3.0,
        min_samples_for_velocity=2,
    )
    window = RunWindow(_RUN_ID)
    events = [
        _llm_call(seq=0, cost_usd=0.01),
        _llm_call(seq=1, cost_usd=0.01),
        _llm_call(seq=2, cost_usd=1.0),  # a 100x spike over the trailing mean
    ]

    detections = _feed(detector, window, events)

    assert len(detections) == 1
    assert detections[0].details["reason"] == "cost_velocity_spike"


def test_budget__velocity_check_needs_min_samples_first() -> None:
    detector = BudgetDetector(
        max_cost_usd=1_000_000.0,
        max_tokens=1_000_000,
        velocity_multiplier=3.0,
        min_samples_for_velocity=2,
    )
    window = RunWindow(_RUN_ID)
    # Only one prior sample before the "spike" — below min_samples_for_velocity.
    events = [_llm_call(seq=0, cost_usd=0.01), _llm_call(seq=1, cost_usd=1.0)]

    detections = _feed(detector, window, events)

    assert detections == []


def test_budget__gradual_steady_cost_does_not_trigger_velocity() -> None:
    """A steady cost per call (no spike) must never look like a velocity
    anomaly, however high the absolute per-call cost is (that's the
    absolute check's job, not velocity's)."""
    detector = BudgetDetector(
        max_cost_usd=1_000_000.0, max_tokens=1_000_000, velocity_multiplier=3.0
    )
    window = RunWindow(_RUN_ID)
    events = [_llm_call(seq=i, cost_usd=0.5) for i in range(10)]

    detections = _feed(detector, window, events)

    assert detections == []


def test_budget__non_llm_events_are_ignored() -> None:
    detector = BudgetDetector(max_cost_usd=0.0, max_tokens=0)
    window = RunWindow(_RUN_ID)
    base: dict[str, Any] = {
        "schema": "trazo.v1",
        "event_id": "evt_x",
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
    event = EventAdapter.validate_python(base)

    window.record(event)
    detection = detector.on_event(event, window)

    assert detection is None
