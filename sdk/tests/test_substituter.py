"""Unit tests for trazo.core.substituter.Substituter (TRZ-P4-02)."""

from __future__ import annotations

from collections import defaultdict

import pytest

from trazo.core.fingerprint import fingerprint_for
from trazo.core.replay_bundle import RecordedEvent, ReplayBundle
from trazo.core.replay_report import ReplayDivergence
from trazo.core.substituter import Substituter


def _event(seq: int, kind: str, payload: dict[str, object]) -> RecordedEvent:
    return RecordedEvent(
        run_id="run_1",
        seq=seq,
        event_id=f"evt_{seq}",
        kind=kind,
        ts="2026-01-01T00:00:00Z",
        step_id=None,
        agent_id=None,
        fingerprint=fingerprint_for(kind, payload),
        payload=payload,
        blobs=[],
    )


def _bundle(events: list[RecordedEvent]) -> ReplayBundle:
    by_kind: dict[str, list[RecordedEvent]] = defaultdict(list)
    for event in events:
        by_kind[event.kind].append(event)
    return ReplayBundle(
        run_id="run_1",
        project_id="proj_1",
        framework="langgraph",
        status="ok",
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:00:05Z",
        tags={},
        totals={},
        event_count=len(events),
        blob_manifest=[],
        events=events,
        _events_by_kind=dict(by_kind),
    )


def _llm_payload(question: str, response: str) -> dict[str, object]:
    return {
        "provider": "fixture",
        "model": "fixture-v1",
        "params": {},
        "messages_in": {"question": question},
        "response": response,
        "tokens_in": 1,
        "tokens_out": 1,
        "cost_usd": 0.0,
        "latency_ms": 1.0,
    }


def test_substitute__exact_match_returns_recorded_result() -> None:
    bundle = _bundle([_event(0, "llm.call", _llm_payload("q1", "a1"))])
    sub = Substituter(bundle)

    result = sub.substitute(
        "llm.call",
        {
            "provider": "fixture",
            "model": "fixture-v1",
            "params": {},
            "messages_in": {"question": "q1"},
        },
    )

    assert result["response"] == "a1"
    assert len(sub.report.steps) == 1
    assert sub.report.steps[0].reordered is False


def test_substitute__advances_cursor_across_repeated_calls() -> None:
    bundle = _bundle(
        [
            _event(0, "llm.call", _llm_payload("q1", "a1")),
            _event(1, "llm.call", _llm_payload("q2", "a2")),
        ]
    )
    sub = Substituter(bundle)

    r1 = sub.substitute(
        "llm.call",
        {
            "provider": "fixture",
            "model": "fixture-v1",
            "params": {},
            "messages_in": {"question": "q1"},
        },
    )
    r2 = sub.substitute(
        "llm.call",
        {
            "provider": "fixture",
            "model": "fixture-v1",
            "params": {},
            "messages_in": {"question": "q2"},
        },
    )

    assert (r1["response"], r2["response"]) == ("a1", "a2")


def test_substitute__lookahead_match_marks_reordered() -> None:
    """A parallel-recorded framework may deliver q2 before q1; matching
    q2 out of order (within LOOKAHEAD) must still succeed, marked
    reordered (REPLAY_ENGINE.md §2)."""
    bundle = _bundle(
        [
            _event(0, "llm.call", _llm_payload("q1", "a1")),
            _event(1, "llm.call", _llm_payload("q2", "a2")),
        ]
    )
    sub = Substituter(bundle)

    result = sub.substitute(
        "llm.call",
        {
            "provider": "fixture",
            "model": "fixture-v1",
            "params": {},
            "messages_in": {"question": "q2"},
        },
    )

    assert result["response"] == "a2"
    assert sub.report.steps[0].reordered is True

    # q1 is still pending and must still be matchable afterward.
    result2 = sub.substitute(
        "llm.call",
        {
            "provider": "fixture",
            "model": "fixture-v1",
            "params": {},
            "messages_in": {"question": "q1"},
        },
    )
    assert result2["response"] == "a1"


def test_substitute__beyond_lookahead_is_a_divergence_not_a_match() -> None:
    bundle = _bundle(
        [_event(i, "llm.call", _llm_payload(f"q{i}", f"a{i}")) for i in range(6)]
    )
    sub = Substituter(bundle, mode="strict")

    with pytest.raises(ReplayDivergence):
        sub.substitute(
            "llm.call",
            {
                "provider": "fixture",
                "model": "fixture-v1",
                "params": {},
                "messages_in": {"question": "q5"},  # 5 positions past the front
            },
        )


def test_substitute__strict_mode_raises_on_mismatch() -> None:
    bundle = _bundle([_event(0, "llm.call", _llm_payload("q1", "a1"))])
    sub = Substituter(bundle, mode="strict")

    with pytest.raises(ReplayDivergence) as exc_info:
        sub.substitute(
            "llm.call",
            {
                "provider": "fixture",
                "model": "fixture-v1",
                "params": {},
                "messages_in": {"question": "different question"},
            },
        )

    assert exc_info.value.kind == "llm.call"
    assert exc_info.value.reason == "mismatch"
    assert len(sub.report.divergences) == 1


def test_substitute__strict_mode_raises_when_cursor_exhausted() -> None:
    bundle = _bundle([])
    sub = Substituter(bundle, mode="strict")

    with pytest.raises(ReplayDivergence) as exc_info:
        sub.substitute(
            "llm.call",
            {
                "provider": "fixture",
                "model": "fixture-v1",
                "params": {},
                "messages_in": {},
            },
        )

    assert exc_info.value.reason == "exhausted"


def test_substitute__lenient_mode_returns_recorded_at_cursor_and_continues() -> None:
    bundle = _bundle([_event(0, "llm.call", _llm_payload("q1", "a1"))])
    sub = Substituter(bundle, mode="lenient")

    result = sub.substitute(
        "llm.call",
        {
            "provider": "fixture",
            "model": "fixture-v1",
            "params": {},
            "messages_in": {"question": "totally different"},
        },
    )

    assert result["response"] == "a1"  # recorded-at-cursor result, returned anyway
    assert len(sub.report.divergences) == 1
    assert len(sub.report.steps) == 0  # a divergence, not a match


def test_substitute__lenient_mode_still_raises_when_nothing_to_fall_back_to() -> None:
    bundle = _bundle([])
    sub = Substituter(bundle, mode="lenient")

    with pytest.raises(ReplayDivergence):
        sub.substitute(
            "llm.call",
            {
                "provider": "fixture",
                "model": "fixture-v1",
                "params": {},
                "messages_in": {},
            },
        )


def test_substitute__invalid_mode_raises_value_error() -> None:
    bundle = _bundle([])

    with pytest.raises(ValueError, match="mode must be"):
        Substituter(bundle, mode="yolo")


def test_substitute__per_kind_cursors_are_independent() -> None:
    bundle = _bundle(
        [
            _event(0, "llm.call", _llm_payload("q1", "a1")),
            _event(
                1,
                "tool.call",
                {
                    "tool_name": "search",
                    "args": {"q": "x"},
                    "result": "r1",
                    "status": "ok",
                    "side_effect_class": "external",
                    "latency_ms": 1.0,
                },
            ),
        ]
    )
    sub = Substituter(bundle)

    tool_result = sub.substitute(
        "tool.call",
        {"tool_name": "search", "args": {"q": "x"}, "side_effect_class": "external"},
    )
    llm_result = sub.substitute(
        "llm.call",
        {
            "provider": "fixture",
            "model": "fixture-v1",
            "params": {},
            "messages_in": {"question": "q1"},
        },
    )

    assert tool_result["result"] == "r1"
    assert llm_result["response"] == "a1"
