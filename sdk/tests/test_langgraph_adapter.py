"""Integration test for the LangGraph adapter (TRZ-P2-04).

DoD: boundary-coverage audit — every LLM/tool call the toy agent makes
must be intercepted (proxy-counted here via the fake LLM/tool's own call
counters, compared against the events actually recorded).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from agents.research_assistant import ToyState, build_toy_graph, initial_state
from langgraph.graph import END, START, StateGraph

from trazo.core.context import init as context_init
from trazo.core.policy import PolicyHook, PolicyMode
from trazo.core.recorder import Recorder
from trazo.decorators import (
    trace_llm,
    trace_memory_read,
    trace_memory_write,
    trace_tool,
)
from trazo.errors import PolicyDenied
from trazo.integrations.langgraph import instrument


class _FakeShipper:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []

    def enqueue(self, event: dict[str, Any]) -> None:
        self.enqueued.append(event)

    def flush_and_stop(self, *, timeout: float = 5.0) -> None:
        pass


def _events_by_kind(events: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [e for e in events if e["kind"] == kind]


def test_instrument__traces_full_toy_agent_run_with_boundary_coverage() -> None:
    context_init(project="toy-agent-test")
    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)
    graph, counters = build_toy_graph()

    traced = instrument(graph, recorder=recorder)
    result = traced.invoke(initial_state())

    assert result["search_result"] == "results for trazo"

    events = shipper.enqueued
    run_started = _events_by_kind(events, "run.started")
    run_finished = _events_by_kind(events, "run.finished")
    step_started = _events_by_kind(events, "step.started")
    step_finished = _events_by_kind(events, "step.finished")
    llm_calls = _events_by_kind(events, "llm.call")
    tool_calls = _events_by_kind(events, "tool.call")

    # --- boundary-coverage audit: every real LLM/tool call was captured ---
    assert len(llm_calls) == counters.llm_calls == 1
    assert len(tool_calls) == counters.tool_calls == 1

    # --- run/step lifecycle shape ---
    assert len(run_started) == 1
    assert len(run_finished) == 1
    assert run_started[0]["payload"]["framework"] == "langgraph"
    assert run_finished[0]["payload"]["status"] == "ok"
    assert run_finished[0]["payload"]["totals"]["llm_calls"] == 1
    assert run_finished[0]["payload"]["totals"]["tool_calls"] == 1

    assert len(step_started) == 2
    assert len(step_finished) == 2
    assert {e["payload"]["name"] for e in step_started} == {"plan", "search"}

    # --- attribution: the llm.call and tool.call landed on the right steps ---
    plan_step_id = next(
        e["step_id"] for e in step_started if e["payload"]["name"] == "plan"
    )
    search_step_id = next(
        e["step_id"] for e in step_started if e["payload"]["name"] == "search"
    )
    assert llm_calls[0]["step_id"] == plan_step_id
    assert llm_calls[0]["agent_id"] == "plan"
    assert tool_calls[0]["step_id"] == search_step_id
    assert tool_calls[0]["agent_id"] == "search"

    # --- fingerprints present on every boundary-critical event ---
    for event in llm_calls + tool_calls:
        assert event["fingerprint"].startswith("sha256:")

    # --- state hashes present on every step event ---
    for event in step_started:
        assert event["payload"]["state_before_hash"].startswith("sha256:")
    for event in step_finished:
        assert event["payload"]["state_after_hash"].startswith("sha256:")

    # --- seq is strictly increasing across the whole run ---
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs)
    assert len(seqs) == len(set(seqs))

    # --- events count in totals matches what was actually recorded ---
    assert run_finished[0]["payload"]["totals"]["events"] == len(events)

    # --- every event is actually JSON-serializable, not just capturable by
    # a fake shipper: `_FakeShipper` above only appends raw dicts, so a
    # non-JSON-safe field (e.g. a raw LangChain message object leaking into
    # a payload) would pass every other assertion here and still crash the
    # real Shipper's background thread the moment it tried to ship a batch
    json.dumps(events)


def test_instrument__last_run_id_matches_every_emitted_events_run_id() -> None:
    """TRZ-P3-05 needs a public way to learn which run_id a completed
    ``.invoke()`` call used (to archive it to the demo corpus index) —
    ``run_scope``'s run_id is otherwise only readable *during* the call,
    via a contextvar that resets the moment ``.invoke()`` returns."""
    context_init(project="toy-agent-test")
    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)
    graph, _counters = build_toy_graph()

    traced = instrument(graph, recorder=recorder)
    traced.invoke(initial_state())

    assert traced.last_run_id is not None
    assert {e["run_id"] for e in shipper.enqueued} == {traced.last_run_id}


def test_instrument__tags_are_recorded_on_run_started() -> None:
    """TRZ-P5-01: the chaos harness tags ground truth
    (``injected_failure``) on the run — instrument() must pass it
    through to run.started's payload verbatim."""
    context_init(project="toy-agent-test")
    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)
    graph, _counters = build_toy_graph()

    traced = instrument(
        graph, recorder=recorder, tags={"injected_failure": {"class": "loop"}}
    )
    traced.invoke(initial_state())

    [run_started] = _events_by_kind(shipper.enqueued, "run.started")
    assert run_started["payload"]["tags"] == {"injected_failure": {"class": "loop"}}


def test_instrument__tags_default_to_empty_dict() -> None:
    context_init(project="toy-agent-test")
    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)
    graph, _counters = build_toy_graph()

    traced = instrument(graph, recorder=recorder)
    traced.invoke(initial_state())

    [run_started] = _events_by_kind(shipper.enqueued, "run.started")
    assert run_started["payload"]["tags"] == {}


def test_instrument__totals_count_escape_hatch_calls_not_just_langchain_callbacks() -> (
    None
):
    """Real bug found running the research-assistant demo for real
    (TRZ-P5-01): its nodes call @trace_llm/@trace_tool-wrapped functions
    directly — Recorder.boundary(), never a genuine LangChain
    on_llm_start/on_tool_start callback — so run.finished.totals'
    llm_calls/tool_calls/tokens were silently always zero for exactly
    this style of node. Totals must come from every boundary call
    Recorder actually shipped, not just ones a real LangChain object's
    callbacks happened to fire for."""
    from trazo.core.runtime import _install_recorder_for_tests

    context_init(project="toy-agent-test")
    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)
    _install_recorder_for_tests(recorder)  # trace_llm/trace_tool use get_recorder()

    @trace_llm(provider="fixture", model="fixture-v1")
    def call_llm(prompt: str) -> dict[str, Any]:
        return {"response": "an answer", "tokens_in": 7, "tokens_out": 3}

    @trace_tool(side_effect_class="external")
    def call_tool(query: str) -> str:
        return f"results for {query}"

    def plan(state: ToyState, config: dict[str, Any]) -> dict[str, Any]:
        call_llm("hello")
        return {}

    def search(state: ToyState, config: dict[str, Any]) -> dict[str, Any]:
        call_tool("trazo")
        return {}

    graph = StateGraph(ToyState)
    graph.add_node("plan", plan)
    graph.add_node("search", search)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "search")
    graph.add_edge("search", END)
    compiled = graph.compile()

    traced = instrument(compiled, recorder=recorder)
    traced.invoke({"messages": [], "search_result": ""})

    [run_finished] = _events_by_kind(shipper.enqueued, "run.finished")
    totals = run_finished["payload"]["totals"]
    assert totals["llm_calls"] == 1
    assert totals["tool_calls"] == 1
    assert totals["tokens_in"] == 7
    assert totals["tokens_out"] == 3


def test_instrument__totals_events_counts_kinds_outside_the_llm_tool_step_set() -> None:
    """Real bug found running the research-assistant demo against a live
    control plane (TRZ-P5-01): ``run.finished.totals.events`` was derived
    arithmetically as ``2 + step_count + llm_calls + tool_calls``, so
    ``memory.read``/``memory.write`` were never counted — a run the store
    held 55 events for reported 49 in its own rollup, and the dashboard
    showed both numbers on the same screen.

    The existing coverage above asserts ``totals["events"] == len(events)``
    but runs a graph emitting only kinds the formula already knew about,
    so it could never catch this. This one emits a memory boundary
    specifically to pin the invariant against *any* kind.
    """
    from trazo.core.runtime import _install_recorder_for_tests

    context_init(project="toy-agent-test")
    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)
    _install_recorder_for_tests(recorder)

    @trace_memory_read(store="vector")
    def recall(query: str) -> list[str]:
        return ["a recollection"]

    @trace_memory_write(store="vector")
    def remember(key_or_ns: str, value: str) -> None:
        return None

    def plan(state: ToyState, config: dict[str, Any]) -> dict[str, Any]:
        recall("what do I know")
        remember("notes", "something learned")
        return {}

    graph = StateGraph(ToyState)
    graph.add_node("plan", plan)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", END)

    traced = instrument(graph.compile(), recorder=recorder)
    traced.invoke({"messages": [], "search_result": ""})

    events = shipper.enqueued
    [run_finished] = _events_by_kind(events, "run.finished")

    assert len(_events_by_kind(events, "memory.read")) == 1
    assert len(_events_by_kind(events, "memory.write")) == 1
    assert run_finished["payload"]["totals"]["events"] == len(events)


def test_instrument__run_error_still_emits_run_finished_with_error_status() -> None:
    context_init(project="toy-agent-test")
    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)

    def _boom_node(state: ToyState, config: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("node exploded")

    graph = StateGraph(ToyState)
    graph.add_node("boom", _boom_node)
    graph.add_edge(START, "boom")
    graph.add_edge("boom", END)
    compiled = graph.compile()

    traced = instrument(compiled, recorder=recorder)

    try:
        traced.invoke({"messages": [], "search_result": ""})
        raised = False
    except RuntimeError:
        raised = True

    assert raised, "the node's real exception must propagate, not be swallowed"
    run_finished = _events_by_kind(shipper.enqueued, "run.finished")
    assert len(run_finished) == 1


def _deny_policy_hook() -> PolicyHook:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"decision": "deny", "policy_id": "tool_blocklist", "reasons": ["x"]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return PolicyHook(
        endpoint="http://example.test",
        api_key="k",
        client=client,
        mode=PolicyMode.ENFORCE,
        governed_side_effect_classes=frozenset({"external"}),
    )


def test_instrument__policy_denied_tool_call_never_actually_executes() -> None:
    """TRZ-P6-04's DoD: "Blocked call provably never executes" — a real
    side-effect sentinel (the toy tool's own call counter, independent of
    anything the recorder observes) proves the tool's body genuinely
    never ran, not just that an event wasn't recorded for it."""
    context_init(project="toy-agent-test")
    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)
    graph, counters = build_toy_graph()

    traced = instrument(graph, recorder=recorder, policy_hook=_deny_policy_hook())

    raised = False
    try:
        traced.invoke(initial_state())
    except PolicyDenied as exc:
        raised = True
        assert exc.decision == "deny"
        assert exc.policy_id == "tool_blocklist"

    assert raised, "PolicyDenied must propagate out of .invoke()"
    assert counters.llm_calls == 1, "the plan node's LLM call is ungoverned, unaffected"
    assert counters.tool_calls == 0, "the tool's real body must never have run"
