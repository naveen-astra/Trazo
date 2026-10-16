"""Unit tests for trazo_server.detectors.base (TRZ-P5-03)."""

from __future__ import annotations

from typing import Any

from trazo_server.detectors.base import RunWindow
from trazo_server.events import Event, EventAdapter

_RUN_ID = "run_01J9Z8QK3V7XG2N4P5R6S7T8VW"


def _event(**overrides: Any) -> Event:
    base: dict[str, Any] = {
        "schema": "trazo.v1",
        "event_id": "evt_01J9Z8QK3V0000000000000001",
        "run_id": _RUN_ID,
        "project": "synthetic-project",
        "seq": 0,
        "ts": "2026-07-18T09:30:00.000Z",
        "kind": "run.started",
        "payload": {
            "framework": "langgraph",
            "framework_version": "0.2.39",
            "sdk_version": "0.1.0",
            "entry_input": {"query": "hi"},
            "tags": {},
        },
    }
    base.update(overrides)
    return EventAdapter.validate_python(base)


def _llm_call(*, seq: int, cost_usd: float, tokens_in: int, tokens_out: int) -> Event:
    return _event(
        event_id=f"evt_llm_{seq}",
        seq=seq,
        kind="llm.call",
        fingerprint=f"sha256:{'a' * 64}",
        payload={
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
    )


def _tool_call(*, seq: int, fingerprint: str) -> Event:
    return _event(
        event_id=f"evt_tool_{seq}",
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


def _step_finished(*, seq: int, state_after_hash: str) -> Event:
    return _event(
        event_id=f"evt_step_{seq}",
        seq=seq,
        kind="step.finished",
        payload={
            "status": "ok",
            "state_after_hash": state_after_hash,
            "state_after": {},
            "duration_ms": 1.0,
        },
    )


def test_record__tracks_boundary_events_in_order() -> None:
    window = RunWindow(_RUN_ID)

    window.record(_tool_call(seq=0, fingerprint=f"sha256:{'a' * 64}"))
    window.record(_tool_call(seq=1, fingerprint=f"sha256:{'b' * 64}"))

    assert [b.event_id for b in window.recent_boundaries] == [
        "evt_tool_0",
        "evt_tool_1",
    ]
    assert [b.fingerprint for b in window.recent_boundaries] == [
        f"sha256:{'a' * 64}",
        f"sha256:{'b' * 64}",
    ]


def test_record__ignores_non_boundary_kinds_for_the_boundary_buffer() -> None:
    window = RunWindow(_RUN_ID)

    window.record(_event(kind="run.started"))

    assert len(window.recent_boundaries) == 0


def test_record__accumulates_cost_and_tokens_from_llm_calls_only() -> None:
    window = RunWindow(_RUN_ID)

    window.record(_llm_call(seq=0, cost_usd=1.5, tokens_in=10, tokens_out=5))
    window.record(_llm_call(seq=1, cost_usd=2.5, tokens_in=20, tokens_out=8))
    window.record(_tool_call(seq=2, fingerprint=f"sha256:{'c' * 64}"))

    assert window.cost_usd_total == 4.0
    assert window.tokens_total == 43  # 10+5+20+8


def test_record__tracks_state_hashes_and_step_count_from_step_finished() -> None:
    window = RunWindow(_RUN_ID)

    window.record(_step_finished(seq=0, state_after_hash=f"sha256:{'1' * 64}"))
    window.record(_step_finished(seq=1, state_after_hash=f"sha256:{'2' * 64}"))

    assert list(window.recent_state_hashes) == [
        f"sha256:{'1' * 64}",
        f"sha256:{'2' * 64}",
    ]
    assert window.step_count == 2


def test_record__ring_buffer_evicts_oldest_past_max_size() -> None:
    window = RunWindow(_RUN_ID, max_size=2)

    window.record(_tool_call(seq=0, fingerprint=f"sha256:{'a' * 64}"))
    window.record(_tool_call(seq=1, fingerprint=f"sha256:{'b' * 64}"))
    window.record(_tool_call(seq=2, fingerprint=f"sha256:{'c' * 64}"))

    assert [b.event_id for b in window.recent_boundaries] == [
        "evt_tool_1",
        "evt_tool_2",
    ]


def test_record__tracks_recent_llm_costs_in_order() -> None:
    window = RunWindow(_RUN_ID)

    window.record(_llm_call(seq=0, cost_usd=1.0, tokens_in=1, tokens_out=1))
    window.record(_llm_call(seq=1, cost_usd=2.0, tokens_in=1, tokens_out=1))

    assert list(window.recent_llm_costs) == [1.0, 2.0]


def test_record__tracks_recent_tool_names_in_order() -> None:
    window = RunWindow(_RUN_ID)

    window.record(_tool_call(seq=0, fingerprint=f"sha256:{'a' * 64}"))
    window.record(_tool_call(seq=1, fingerprint=f"sha256:{'b' * 64}"))

    assert list(window.recent_tool_names) == ["web_search", "web_search"]


def test_record__tracks_recent_tool_fingerprints_in_order() -> None:
    window = RunWindow(_RUN_ID)

    window.record(_tool_call(seq=0, fingerprint=f"sha256:{'a' * 64}"))
    window.record(_tool_call(seq=1, fingerprint=f"sha256:{'b' * 64}"))

    assert list(window.recent_tool_fingerprints) == [
        f"sha256:{'a' * 64}",
        f"sha256:{'b' * 64}",
    ]


def test_as_summary__is_json_safe() -> None:
    import json

    window = RunWindow(_RUN_ID)
    window.record(_llm_call(seq=0, cost_usd=1.0, tokens_in=1, tokens_out=1))

    json.dumps(window.as_summary())  # must not raise


def test_record__counts_a_redelivered_event_once() -> None:
    """A redelivered event (bus reclaim after a failed attempt) must not be
    folded in twice: the totals are cumulative for the rest of the run, so
    a double count inflates cost and can raise a false budget detection."""
    window = RunWindow("run_1")
    call = _llm_call(seq=0, cost_usd=0.5, tokens_in=10, tokens_out=5)

    assert window.record(call) is True
    assert window.record(call) is False

    assert window.cost_usd_total == 0.5
    assert window.tokens_total == 15
    assert len(window.recent_boundaries) == 1
