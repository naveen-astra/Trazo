"""Mutation-localization tests (TRZ-P4-03's DoD): given a recorded run and
a *mutated* re-drive (a prompt edited, a tool arg edited, or two
independent calls reordered), the reported divergence must pinpoint
exactly which call diverged — not just "something, somewhere" — and a
benign reorder within lookahead must *not* be reported as a divergence
at all.
"""

from __future__ import annotations

from collections import defaultdict

import pytest

from trazo.core.fingerprint import fingerprint_for
from trazo.core.replay_bundle import RecordedEvent, ReplayBundle
from trazo.core.replay_report import ReplayDivergence
from trazo.core.substituter import Substituter


def _llm_event(seq: int, question: str, response: str) -> RecordedEvent:
    payload = {
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
    return RecordedEvent(
        run_id="run_1",
        seq=seq,
        event_id=f"evt_{seq}",
        kind="llm.call",
        ts="2026-01-01T00:00:00Z",
        step_id=None,
        agent_id=None,
        fingerprint=fingerprint_for("llm.call", payload),
        payload=payload,
        blobs=[],
    )


def _tool_event(seq: int, query: str, result: str) -> RecordedEvent:
    payload = {
        "tool_name": "web_search",
        "args": {"query": query},
        "side_effect_class": "external",
        "result": result,
        "status": "ok",
        "latency_ms": 1.0,
    }
    return RecordedEvent(
        run_id="run_1",
        seq=seq,
        event_id=f"evt_{seq}",
        kind="tool.call",
        ts="2026-01-01T00:00:00Z",
        step_id=None,
        agent_id=None,
        fingerprint=fingerprint_for("tool.call", payload),
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


def test_prompt_edit__localizes_to_the_exact_call_that_changed() -> None:
    """Three sequential llm.call boundaries; only the *second* prompt was
    edited since recording. The first must replay clean, the second must
    diverge pointing at exactly seq=1 (not seq=0 or seq=2)."""
    bundle = _bundle(
        [
            _llm_event(0, "step one", "a1"),
            _llm_event(1, "step two", "a2"),
            _llm_event(2, "step three", "a3"),
        ]
    )
    sub = Substituter(bundle, mode="strict")

    # Call 1: unchanged, matches fine.
    result0 = sub.substitute(
        "llm.call",
        {
            "provider": "fixture",
            "model": "fixture-v1",
            "params": {},
            "messages_in": {"question": "step one"},
        },
    )
    assert result0["response"] == "a1"

    # Call 2: prompt drifted since recording.
    with pytest.raises(ReplayDivergence) as exc_info:
        sub.substitute(
            "llm.call",
            {
                "provider": "fixture",
                "model": "fixture-v1",
                "params": {},
                "messages_in": {"question": "step two, but edited"},
            },
        )

    assert exc_info.value.detail.expected_seq == 1
    assert exc_info.value.detail.expected_event_id == "evt_1"
    assert len(sub.report.steps) == 1  # only call 1 ever matched
    assert len(sub.report.divergences) == 1


def test_tool_arg_edit__localizes_to_the_exact_call_that_changed() -> None:
    bundle = _bundle(
        [
            _tool_event(0, "trazo overview", "r1"),
            _tool_event(1, "trazo architecture", "r2"),
        ]
    )
    sub = Substituter(bundle, mode="strict")

    result0 = sub.substitute(
        "tool.call",
        {
            "tool_name": "web_search",
            "args": {"query": "trazo overview"},
            "side_effect_class": "external",
        },
    )
    assert result0["result"] == "r1"

    with pytest.raises(ReplayDivergence) as exc_info:
        sub.substitute(
            "tool.call",
            {
                "tool_name": "web_search",
                "args": {"query": "trazo architecture, edited"},
                "side_effect_class": "external",
            },
        )

    assert exc_info.value.detail.expected_seq == 1
    assert exc_info.value.kind == "tool.call"


def test_benign_reorder_within_lookahead_is_not_reported_as_a_divergence() -> None:
    """Two independent llm.call boundaries whose *code order* flipped
    since recording (e.g. a framework that parallelizes two branches) —
    this must be silently tolerated via lookahead, not reported as a
    mutation."""
    bundle = _bundle([_llm_event(0, "branch a", "a1"), _llm_event(1, "branch b", "a2")])
    sub = Substituter(bundle, mode="strict")

    # Live code now asks for "branch b" first, then "branch a".
    result_b = sub.substitute(
        "llm.call",
        {
            "provider": "fixture",
            "model": "fixture-v1",
            "params": {},
            "messages_in": {"question": "branch b"},
        },
    )
    result_a = sub.substitute(
        "llm.call",
        {
            "provider": "fixture",
            "model": "fixture-v1",
            "params": {},
            "messages_in": {"question": "branch a"},
        },
    )

    assert (result_b["response"], result_a["response"]) == ("a2", "a1")
    assert sub.report.divergences == []
    assert sub.report.reordered_count == 1
    assert sub.report.fidelity == 1.0
