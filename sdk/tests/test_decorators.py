"""Unit tests for @trace_tool / @trace_llm (TRZ-P2-05).

DoD: "used in one test agent" — ``test_custom_agent__traces_full_run``
builds a small hand-rolled agent (no framework adapter) using both
decorators and asserts the full recorded event sequence.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from trazo.core.context import run_scope
from trazo.core.policy import PolicyHook, PolicyMode
from trazo.core.recorder import Recorder, RecorderMode
from trazo.core.replay_bundle import RecordedEvent, ReplayBundle
from trazo.core.substituter import Substituter
from trazo.decorators import (
    trace_llm,
    trace_memory_read,
    trace_memory_write,
    trace_tool,
)
from trazo.errors import PolicyDenied


class _FakeShipper:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []

    def enqueue(self, event: dict[str, Any]) -> None:
        self.enqueued.append(event)

    def flush_and_stop(self, *, timeout: float = 5.0) -> None:
        pass


def _install_recorder() -> tuple[Recorder, _FakeShipper]:
    """trace_tool/trace_llm call trazo.core.runtime.get_recorder(), so the
    test installs one directly rather than going through trazo.init()
    (which would spin up a real network-facing Shipper thread)."""
    from trazo.core.runtime import _install_recorder_for_tests

    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)
    _install_recorder_for_tests(recorder)
    return recorder, shipper


def test_trace_tool__records_a_tool_call_and_returns_the_real_value() -> None:
    _install_recorder()

    @trace_tool(side_effect_class="read")
    def lookup(key: str) -> str:
        return f"value-for-{key}"

    with run_scope("proj"):
        result = lookup("k1")

    assert result == "value-for-k1"


def test_trace_tool__deny_decision_blocks_the_call_in_enforce_mode() -> None:
    """The exact gap a live demo run surfaced: @trace_tool -- SDK.md §1's
    "escape hatch for custom agents" -- never called PolicyHook.check()
    at all, so a governed action executed through it bypassed policy
    enforcement entirely regardless of mode. Confirmed live before this
    fix: a demo using only this decorator for its tools ran $108 over a
    $5 cost cap in enforce mode with zero policy decisions ever made."""
    from trazo.core.runtime import _install_policy_hook_for_tests

    _install_recorder()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={"decision": "deny", "policy_id": "cost_cap", "reasons": ["over cap"]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    _install_policy_hook_for_tests(
        PolicyHook(
            endpoint="http://example.test",
            api_key="k",
            mode=PolicyMode.ENFORCE,
            client=client,
        )
    )

    executed = False

    @trace_tool(side_effect_class="external")
    def spend(amount: float) -> None:
        nonlocal executed
        executed = True

    with run_scope("proj"), pytest.raises(PolicyDenied) as exc_info:
        spend(999.0)

    assert len(calls) == 1
    assert executed is False
    assert exc_info.value.policy_id == "cost_cap"


def test_trace_tool__emits_a_schema_shaped_event() -> None:
    _, shipper = _install_recorder()

    @trace_tool(side_effect_class="write")
    def save(key: str, value: str) -> dict[str, str]:
        return {"saved": key}

    with run_scope("proj"):
        save("k1", value="v1")

    [event] = shipper.enqueued
    assert event["kind"] == "tool.call"
    assert event["payload"]["tool_name"] == "save"
    assert event["payload"]["args"] == {"key": "k1", "value": "v1"}
    assert event["payload"]["side_effect_class"] == "write"
    assert event["payload"]["result"] == {"saved": "k1"}
    assert event["fingerprint"].startswith("sha256:")


def test_trace_tool__custom_name_overrides_function_name() -> None:
    _, shipper = _install_recorder()

    @trace_tool(name="custom.tool.name")
    def fn() -> None:
        return None

    with run_scope("proj"):
        fn()

    assert shipper.enqueued[0]["payload"]["tool_name"] == "custom.tool.name"


def test_trace_tool__exception_propagates_and_nothing_is_recorded() -> None:
    _, shipper = _install_recorder()

    @trace_tool()
    def fails() -> None:
        raise ValueError("boom")

    with run_scope("proj"), pytest.raises(ValueError, match="boom"):
        fails()

    assert shipper.enqueued == []


def test_trace_llm__records_llm_call_and_returns_the_real_value() -> None:
    _, shipper = _install_recorder()

    @trace_llm(provider="openai", model="gpt-4o-mini")
    def ask(question: str) -> dict[str, Any]:
        return {"response": f"answer to {question}", "tokens_in": 5, "tokens_out": 3}

    with run_scope("proj"):
        result = ask("what is trazo?")

    assert result == {
        "response": "answer to what is trazo?",
        "tokens_in": 5,
        "tokens_out": 3,
    }
    [event] = shipper.enqueued
    assert event["kind"] == "llm.call"
    assert event["payload"]["provider"] == "openai"
    assert event["payload"]["model"] == "gpt-4o-mini"
    assert event["payload"]["messages_in"] == {"question": "what is trazo?"}
    assert event["payload"]["tokens_in"] == 5
    assert event["payload"]["tokens_out"] == 3
    assert event["fingerprint"].startswith("sha256:")


def test_trace_llm__non_dict_return_becomes_the_response_verbatim() -> None:
    _, shipper = _install_recorder()

    @trace_llm(provider="anthropic", model="claude")
    def ask(question: str) -> str:
        return "a plain string answer"

    with run_scope("proj"):
        result = ask("hi")

    assert result == "a plain string answer"
    assert shipper.enqueued[0]["payload"]["response"] == "a plain string answer"
    assert shipper.enqueued[0]["payload"]["tokens_in"] == 0


def test_trace_memory_read__records_memory_read_and_returns_results() -> None:
    _, shipper = _install_recorder()

    @trace_memory_read(store="vector")
    def query_memory(query: str, k: int) -> list[str]:
        return [f"result-for-{query}"]

    with run_scope("proj"):
        result = query_memory("what is trazo?", k=3)

    assert result == ["result-for-what is trazo?"]
    [event] = shipper.enqueued
    assert event["kind"] == "memory.read"
    assert event["payload"]["store"] == "vector"
    assert event["payload"]["query"] == "what is trazo?"
    assert event["payload"]["k"] == 3
    assert event["payload"]["results"] == ["result-for-what is trazo?"]
    assert event["fingerprint"].startswith("sha256:")


def test_trace_memory_read__falls_back_to_full_args_when_no_query_param() -> None:
    _, shipper = _install_recorder()

    @trace_memory_read()
    def lookup(a: str, b: str) -> str:
        return "x"

    with run_scope("proj"):
        lookup("1", "2")

    assert shipper.enqueued[0]["payload"]["query"] == {"a": "1", "b": "2"}


def test_trace_memory_write__records_memory_write_and_returns_the_real_value() -> None:
    _, shipper = _install_recorder()

    @trace_memory_write(store="vector")
    def save_memory(key_or_ns: str, value: str) -> bool:
        return True

    with run_scope("proj"):
        result = save_memory("researcher", value="trazo is an SDK")

    assert result is True
    [event] = shipper.enqueued
    assert event["kind"] == "memory.write"
    assert event["payload"]["store"] == "vector"
    assert event["payload"]["key_or_ns"] == "researcher"
    assert event["payload"]["value"] == "trazo is an SDK"
    assert event["fingerprint"].startswith("sha256:")


def test_trace_memory_write__defaults_key_or_ns_when_absent() -> None:
    _, shipper = _install_recorder()

    @trace_memory_write()
    def save(value: str) -> None:
        return None

    with run_scope("proj"):
        save("trazo is an SDK")

    assert shipper.enqueued[0]["payload"]["key_or_ns"] == "default"
    assert shipper.enqueued[0]["payload"]["value"] == "trazo is an SDK"


def test_trace_memory_write__replay_mode_returns_none_without_calling_fn() -> None:
    """memory.write's recorded payload has no return-value field to
    reconstruct (EVENTS.md §2.3) — REPLAY mode must return None, matching
    every real write function's actual return value, and must not call
    fn at all (TRZ-P4-02)."""
    _, record_shipper = _install_recorder()
    live_call_count = 0

    @trace_memory_write()
    def save(value: str) -> None:
        nonlocal live_call_count
        live_call_count += 1
        return None

    with run_scope("proj"):
        save("trazo is an SDK")
    assert live_call_count == 1

    event = _as_recorded_event(record_shipper.enqueued[0])
    bundle = ReplayBundle(
        run_id=event.run_id,
        project_id="proj",
        framework="custom",
        status="ok",
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:00:05Z",
        tags={},
        totals={},
        event_count=1,
        blob_manifest=[],
        events=[event],
        _events_by_kind={"memory.write": [event]},
    )
    replay_recorder = Recorder(
        shipper=_FakeShipper(),
        mode=RecorderMode.REPLAY,
        substituter=Substituter(bundle),
    )
    from trazo.core.runtime import _install_recorder_for_tests

    _install_recorder_for_tests(replay_recorder)

    with run_scope("proj"):
        result = save("trazo is an SDK")

    assert result is None
    assert live_call_count == 1  # unchanged: fn never ran during replay


def test_custom_agent__traces_full_run() -> None:
    """A hand-rolled 'agent' with no framework adapter — the escape hatch
    this task exists for."""
    _, shipper = _install_recorder()

    @trace_llm(provider="openai", model="gpt-4o-mini")
    def call_llm(prompt: str) -> dict[str, Any]:
        return {"response": "search for trazo docs", "tokens_in": 10, "tokens_out": 4}

    @trace_tool(side_effect_class="external")
    def web_search(query: str) -> str:
        return f"results for {query}"

    def run_custom_agent(user_input: str) -> str:
        with run_scope("custom-agent-test"):
            plan = call_llm(user_input)
            search_results = web_search(plan["response"])
            return search_results

    final = run_custom_agent("find trazo")

    assert final == "results for search for trazo docs"
    kinds = [e["kind"] for e in shipper.enqueued]
    assert kinds == ["llm.call", "tool.call"]
    assert shipper.enqueued[0]["seq"] == 0
    assert shipper.enqueued[1]["seq"] == 1
    assert shipper.enqueued[0]["run_id"] == shipper.enqueued[1]["run_id"]


def _as_recorded_event(envelope: dict[str, Any]) -> RecordedEvent:
    return RecordedEvent(
        run_id=envelope["run_id"],
        seq=envelope["seq"],
        event_id=envelope["event_id"],
        kind=envelope["kind"],
        ts=envelope["ts"],
        step_id=envelope.get("step_id"),
        agent_id=envelope.get("agent_id"),
        fingerprint=envelope.get("fingerprint"),
        payload=envelope["payload"],
        blobs=[],
    )


def test_custom_agent__record_then_replay_round_trip_makes_zero_live_calls() -> None:
    """TRZ-P4-02's DoD: record->replay of a scripted toy run has zero
    divergence and zero live calls (network guard). ``@trace_llm``/
    ``@trace_tool`` are the escape hatch this task's own toy agent uses —
    this proves boundary() substitution actually works through them, not
    just through Recorder.boundary() called directly."""
    _, record_shipper = _install_recorder()

    live_call_count = 0

    @trace_llm(provider="openai", model="gpt-4o-mini")
    def call_llm(prompt: str) -> dict[str, Any]:
        nonlocal live_call_count
        live_call_count += 1
        return {"response": "search for trazo docs", "tokens_in": 10, "tokens_out": 4}

    @trace_tool(side_effect_class="external")
    def web_search(query: str) -> str:
        nonlocal live_call_count
        live_call_count += 1
        return f"results for {query}"

    def run_custom_agent(user_input: str) -> str:
        with run_scope("custom-agent-test"):
            plan = call_llm(user_input)
            return web_search(plan["response"])

    # --- record ---
    original_final = run_custom_agent("find trazo")
    assert live_call_count == 2

    events = [_as_recorded_event(e) for e in record_shipper.enqueued]
    bundle = ReplayBundle(
        run_id=events[0].run_id,
        project_id="proj",
        framework="custom",
        status="ok",
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:00:05Z",
        tags={},
        totals={},
        event_count=len(events),
        blob_manifest=[],
        events=events,
        _events_by_kind={
            "llm.call": [e for e in events if e.kind == "llm.call"],
            "tool.call": [e for e in events if e.kind == "tool.call"],
        },
    )

    # --- replay ---
    substituter = Substituter(bundle)
    replay_shipper = _FakeShipper()
    replay_recorder = Recorder(
        shipper=replay_shipper, mode=RecorderMode.REPLAY, substituter=substituter
    )
    from trazo.core.runtime import _install_recorder_for_tests

    _install_recorder_for_tests(replay_recorder)

    replayed_final = run_custom_agent("find trazo")

    assert replayed_final == original_final
    assert live_call_count == 2  # unchanged: neither fn ran again during replay
    assert replay_shipper.enqueued == []  # replays are read-only over history
    assert substituter.report.fidelity == 1.0
    assert substituter.report.divergences == []
