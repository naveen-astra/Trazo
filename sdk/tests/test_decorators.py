"""Unit tests for @trace_tool / @trace_llm (TRZ-P2-05).

DoD: "used in one test agent" — ``test_custom_agent__traces_full_run``
builds a small hand-rolled agent (no framework adapter) using both
decorators and asserts the full recorded event sequence.
"""

from __future__ import annotations

from typing import Any

import pytest

from trazo.core.context import run_scope
from trazo.core.recorder import Recorder
from trazo.decorators import trace_llm, trace_tool


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
