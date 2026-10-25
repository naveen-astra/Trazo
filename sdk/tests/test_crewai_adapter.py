"""Integration test for the CrewAI adapter (TRZ-P3-01).

DoD: boundary-coverage audit — every LLM/tool call the toy crew makes must
be intercepted. Fake LLMs drive ``crewai_event_bus`` exactly the way a
real provider does (``BaseLLM._emit_call_started_event`` etc.) and use the
documented ReAct text format (``crewai.agents.parser``) rather than
CrewAI's native-function-calling internals, which are not a documented,
stable contract (see ``listener.py``'s module docstring).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from crewai import Agent, Crew, Process, Task
from crewai.llms.base_llm import BaseLLM, LLMCallType, llm_call_context
from pydantic import Field

from trazo.core.context import init as context_init
from trazo.core.policy import PolicyHook, PolicyMode
from trazo.core.recorder import Recorder
from trazo.errors import PolicyDenied
from trazo.integrations.crewai import instrument


class _FakeShipper:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []

    def enqueue(self, event: dict[str, Any]) -> None:
        self.enqueued.append(event)

    def flush_and_stop(self, *, timeout: float = 5.0) -> None:
        pass


class _ScriptedLLM(BaseLLM):
    """Fake LLM driving crewai_event_bus exactly like a real provider's
    ``call()`` would, returning canned ReAct-format text (Thought/Action/
    Action Input, or Final Answer) from ``script`` in order."""

    model: str = "fake-model"
    script: list[str] = Field(default_factory=list)
    _step: int = 0

    def call(
        self,
        messages: Any,
        tools: Any = None,
        callbacks: Any = None,
        available_functions: Any = None,
        from_task: Any = None,
        from_agent: Any = None,
        response_model: Any = None,
    ) -> str:
        # A real provider's call() runs inside llm_call_context() so
        # started/completed share one call_id (crewai/llms/base_llm.py) —
        # without it, get_current_call_id() mints a fresh fallback UUID
        # on *every* call, so started/completed never pair up.
        with llm_call_context():
            self._emit_call_started_event(
                messages=messages,
                tools=tools,
                callbacks=callbacks,
                available_functions=available_functions,
                from_task=from_task,
                from_agent=from_agent,
            )
            reply = self.script[self._step]
            self._step += 1
            self._emit_call_completed_event(
                response=reply,
                call_type=LLMCallType.LLM_CALL,
                from_task=from_task,
                from_agent=from_agent,
                messages=messages,
                usage={"prompt_tokens": 10, "completion_tokens": 5},
            )
            return reply


def _events_by_kind(events: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [e for e in events if e["kind"] == kind]


def test_instrument__traces_toy_crew_run_with_boundary_coverage() -> None:
    context_init(project="toy-crew-test")
    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)

    researcher = Agent(
        role="Researcher",
        goal="Find facts",
        backstory="A careful researcher",
        llm=_ScriptedLLM(
            model="fake-model",
            script=[
                "Thought: I should search\n"
                "Action: web_search\n"
                'Action Input: {"query": "trazo"}',
                "Final Answer: found some facts about trazo",
            ],
        ),
        allow_delegation=False,
        verbose=False,
        tools=[_web_search_tool()],
    )
    task = Task(
        description="Research trazo",
        expected_output="facts about trazo",
        agent=researcher,
    )
    crew = Crew(
        agents=[researcher], tasks=[task], process=Process.sequential, verbose=False
    )

    traced = instrument(crew, recorder=recorder)
    result = traced.kickoff()

    assert result.raw == "found some facts about trazo"

    events = shipper.enqueued
    run_started = _events_by_kind(events, "run.started")
    run_finished = _events_by_kind(events, "run.finished")
    step_started = _events_by_kind(events, "step.started")
    step_finished = _events_by_kind(events, "step.finished")
    llm_calls = _events_by_kind(events, "llm.call")
    tool_calls = _events_by_kind(events, "tool.call")

    # --- boundary-coverage audit: one search call, both LLM turns captured ---
    assert len(llm_calls) == 2
    assert len(tool_calls) == 1
    assert tool_calls[0]["payload"]["tool_name"] == "web_search"
    assert tool_calls[0]["payload"]["args"] == {"query": "trazo"}
    assert tool_calls[0]["payload"]["result"] == "results for trazo"

    # --- run/step lifecycle shape ---
    assert len(run_started) == 1
    assert len(run_finished) == 1
    assert run_started[0]["payload"]["framework"] == "crewai"
    assert run_finished[0]["payload"]["status"] == "ok"
    assert run_finished[0]["payload"]["totals"]["llm_calls"] == 2
    assert run_finished[0]["payload"]["totals"]["tool_calls"] == 1
    assert run_finished[0]["payload"]["totals"]["events"] == len(events)

    assert len(step_started) == 1
    assert len(step_finished) == 1
    assert step_started[0]["payload"]["name"] == "Research trazo"
    assert step_finished[0]["payload"]["status"] == "ok"

    # --- attribution: llm.call/tool.call land on the one step, right agent ---
    step_id = step_started[0]["step_id"]
    assert all(e["step_id"] == step_id for e in llm_calls + tool_calls)
    assert all(e["agent_id"] == "Researcher" for e in llm_calls + tool_calls)

    # --- fingerprints present on every boundary-critical event ---
    for event in llm_calls + tool_calls:
        assert event["fingerprint"].startswith("sha256:")

    # --- state hashes present on step events ---
    assert step_started[0]["payload"]["state_before_hash"].startswith("sha256:")
    assert step_finished[0]["payload"]["state_after_hash"].startswith("sha256:")

    # --- seq is strictly increasing across the whole run ---
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs)
    assert len(seqs) == len(set(seqs))

    # --- every event is actually JSON-serializable (see LangGraph adapter's
    # entry_input regression: a fake shipper bypasses this check entirely) ---
    json.dumps(events)


def test_instrument__last_run_id_matches_every_emitted_events_run_id() -> None:
    """TRZ-P3-05 needs a public way to learn which run_id a completed
    ``.kickoff()`` call used (to archive it to the demo corpus index) —
    ``run_scope``'s run_id is otherwise only readable *during* the call,
    via a contextvar that resets the moment ``.kickoff()`` returns."""
    context_init(project="toy-crew-test")
    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)

    researcher = Agent(
        role="Researcher",
        goal="Find facts",
        backstory="A careful researcher",
        llm=_ScriptedLLM(model="fake-model", script=["Final Answer: found some facts"]),
        allow_delegation=False,
        verbose=False,
    )
    task = Task(
        description="Research trazo",
        expected_output="facts about trazo",
        agent=researcher,
    )
    crew = Crew(
        agents=[researcher], tasks=[task], process=Process.sequential, verbose=False
    )

    traced = instrument(crew, recorder=recorder)
    traced.kickoff()

    assert traced.last_run_id is not None
    assert {e["run_id"] for e in shipper.enqueued} == {traced.last_run_id}


def test_instrument__tags_are_recorded_on_run_started() -> None:
    """TRZ-P5-01: the chaos harness tags ground truth (injected_failure)
    on the run — instrument() must pass it through verbatim."""
    context_init(project="toy-crew-test")
    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)

    researcher = Agent(
        role="Researcher",
        goal="Find facts",
        backstory="A careful researcher",
        llm=_ScriptedLLM(model="fake-model", script=["Final Answer: found some facts"]),
        allow_delegation=False,
        verbose=False,
    )
    task = Task(
        description="Research trazo",
        expected_output="facts about trazo",
        agent=researcher,
    )
    crew = Crew(
        agents=[researcher], tasks=[task], process=Process.sequential, verbose=False
    )

    traced = instrument(
        crew, recorder=recorder, tags={"injected_failure": {"class": "budget"}}
    )
    traced.kickoff()

    [run_started] = _events_by_kind(shipper.enqueued, "run.started")
    assert run_started["payload"]["tags"] == {"injected_failure": {"class": "budget"}}


def test_instrument__delegation_emits_agent_message_not_tool_call() -> None:
    context_init(project="toy-crew-test")
    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)

    researcher = Agent(
        role="Researcher",
        goal="Find facts",
        backstory="A careful researcher",
        llm=_ScriptedLLM(
            model="fake-model", script=["Final Answer: found some facts about trazo"]
        ),
        allow_delegation=False,
        verbose=False,
    )
    writer = Agent(
        role="Writer",
        goal="Write a summary",
        backstory="A concise writer",
        llm=_ScriptedLLM(
            model="fake-model",
            script=[
                "Thought: I should delegate\n"
                "Action: Delegate work to coworker\n"
                'Action Input: {"task": "research trazo", "context": "need facts", '
                '"coworker": "Researcher"}',
                "Final Answer: summary based on delegated research",
            ],
        ),
        allow_delegation=True,
        verbose=False,
    )
    task = Task(
        description="Write a summary about trazo",
        expected_output="a summary",
        agent=writer,
    )
    crew = Crew(
        agents=[researcher, writer],
        tasks=[task],
        process=Process.sequential,
        verbose=False,
    )

    traced = instrument(crew, recorder=recorder)
    result = traced.kickoff()

    assert result.raw == "summary based on delegated research"

    events = shipper.enqueued
    messages = _events_by_kind(events, "agent.message")
    tool_calls = _events_by_kind(events, "tool.call")

    assert len(messages) == 1
    assert len(tool_calls) == 0  # delegation must not also surface as a tool.call
    assert messages[0]["payload"]["from_agent"] == "Writer"
    assert messages[0]["payload"]["to_agent"] == "Researcher"
    assert messages[0]["payload"]["message_type"] == "delegation"
    assert messages[0]["payload"]["content"]["task"] == "research trazo"
    json.dumps(events)


def test_instrument__run_error_still_emits_run_finished_with_error_status() -> None:
    context_init(project="toy-crew-test")
    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)

    researcher = Agent(
        role="Researcher",
        goal="Find facts",
        backstory="A careful researcher",
        llm=_ScriptedLLM(
            model="fake-model", script=[]
        ),  # empty script -> IndexError inside call()
        allow_delegation=False,
        verbose=False,
    )
    task = Task(
        description="Research trazo",
        expected_output="facts about trazo",
        agent=researcher,
    )
    crew = Crew(
        agents=[researcher], tasks=[task], process=Process.sequential, verbose=False
    )

    traced = instrument(crew, recorder=recorder)

    try:
        traced.kickoff()
        raised = False
    except Exception:
        raised = True

    assert raised, "the crew's real exception must propagate, not be swallowed"
    run_finished = _events_by_kind(shipper.enqueued, "run.finished")
    assert len(run_finished) == 1
    assert run_finished[0]["payload"]["status"] == "error"


def _web_search_tool() -> Any:
    from crewai.tools import BaseTool

    class _SearchTool(BaseTool):
        name: str = "web_search"
        description: str = "Search the web for a query"

        def _run(self, query: str) -> str:
            return f"results for {query}"

    return _SearchTool()


class _CountingTool:
    """Builds a web_search tool whose body counts its own executions -- a
    side-effect sentinel independent of anything the recorder observes."""

    def __init__(self) -> None:
        self.executions = 0

    def build(self) -> Any:
        from crewai.tools import BaseTool

        sentinel = self

        class _SearchTool(BaseTool):
            name: str = "web_search"
            description: str = "Search the web for a query"

            def _run(self, query: str) -> str:
                sentinel.executions += 1
                return f"results for {query}"

        return _SearchTool()


def _policy_hook(decision: str) -> PolicyHook:
    checked: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        checked.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "decision": decision,
                "policy_id": "tool_blocklist",
                "reasons": ["x"],
            },
        )

    hook = PolicyHook(
        endpoint="http://example.test",
        api_key="k",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        mode=PolicyMode.ENFORCE,
        governed_side_effect_classes=frozenset({"external"}),
    )
    hook.checked = checked  # type: ignore[attr-defined]
    return hook


def _searching_crew(tool: Any) -> Crew:
    researcher = Agent(
        role="Researcher",
        goal="Find facts",
        backstory="A careful researcher",
        llm=_ScriptedLLM(
            model="fake-model",
            script=[
                "Thought: I should search\n"
                "Action: web_search\n"
                'Action Input: {"query": "trazo"}',
                *["Final Answer: done"] * 5,
            ],
        ),
        allow_delegation=False,
        verbose=False,
        tools=[tool],
    )
    task = Task(
        description="Research trazo",
        expected_output="facts about trazo",
        agent=researcher,
    )
    return Crew(
        agents=[researcher], tasks=[task], process=Process.sequential, verbose=False
    )


def test_instrument__policy_denied_tool_call_never_actually_executes() -> None:
    """TRZ-P6-04's DoD for CrewAI: the denied tool's body never runs, and
    PolicyDenied reaches the caller even though CrewAI itself catches tool
    exceptions and only reports them to the agent."""
    context_init(project="toy-crew-test")
    shipper = _FakeShipper()
    counting = _CountingTool()
    tool = counting.build()
    hook = _policy_hook("deny")
    traced = instrument(
        _searching_crew(tool), recorder=Recorder(shipper=shipper), policy_hook=hook
    )

    with pytest.raises(PolicyDenied) as exc_info:
        traced.kickoff()

    assert exc_info.value.policy_id == "tool_blocklist"
    assert counting.executions == 0, "the tool's real body must never have run"
    checked = hook.checked  # type: ignore[attr-defined]
    assert checked, "the policy endpoint must have been asked"
    assert checked[0]["action"]["tool_name"] == "web_search"
    run_finished = _events_by_kind(shipper.enqueued, "run.finished")
    assert [e["payload"]["status"] for e in run_finished] == ["error"]
    assert "_run" not in tool.__dict__, "the policy wrapper must be removed"


def test_instrument__policy_allowed_tool_call_runs_normally() -> None:
    context_init(project="toy-crew-test")
    shipper = _FakeShipper()
    counting = _CountingTool()
    tool = counting.build()
    traced = instrument(
        _searching_crew(tool),
        recorder=Recorder(shipper=shipper),
        policy_hook=_policy_hook("allow"),
    )

    result = traced.kickoff()

    assert result.raw == "done"
    assert counting.executions == 1
    tool_calls = _events_by_kind(shipper.enqueued, "tool.call")
    assert [e["payload"]["result"] for e in tool_calls] == ["results for trazo"]
    assert "_run" not in tool.__dict__


def test_instrument__without_a_policy_hook_tools_are_left_untouched() -> None:
    context_init(project="toy-crew-test")
    counting = _CountingTool()
    tool = counting.build()
    traced = instrument(
        _searching_crew(tool), recorder=Recorder(shipper=_FakeShipper())
    )

    traced.kickoff()

    assert counting.executions == 1


def test_instrument__llm_calls_are_priced_from_the_model_and_tokens() -> None:
    context_init(project="toy-crew-test")
    shipper = _FakeShipper()
    agent = Agent(
        role="Writer",
        goal="Write",
        backstory="A writer",
        llm=_ScriptedLLM(model="gpt-4o-mini", script=["Final Answer: done"]),
        allow_delegation=False,
        verbose=False,
    )
    task = Task(description="Write", expected_output="text", agent=agent)
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential)

    instrument(crew, recorder=Recorder(shipper=shipper)).kickoff()

    [llm_call] = _events_by_kind(shipper.enqueued, "llm.call")
    # _ScriptedLLM reports 10 prompt and 5 completion tokens.
    assert llm_call["payload"]["cost_usd"] == pytest.approx(
        (10 * 0.15 + 5 * 0.60) / 1_000_000
    )
    [run_finished] = _events_by_kind(shipper.enqueued, "run.finished")
    assert run_finished["payload"]["totals"]["cost_usd"] == pytest.approx(
        llm_call["payload"]["cost_usd"]
    )


def _hierarchical_crew(tool: Any, worker_script: list[str]) -> Crew:
    """A manager delegates to one worker. The manager and the worker each
    get their own scripted model, so the calls are told apart by model."""
    worker = Agent(
        role="Researcher",
        goal="Find facts",
        backstory="A careful researcher",
        llm=_ScriptedLLM(model="fake-worker", script=worker_script),
        allow_delegation=False,
        verbose=False,
        tools=[tool],
    )
    manager_llm = _ScriptedLLM(
        model="fake-manager",
        script=[
            "Thought: I should delegate\n"
            "Action: Delegate work to coworker\n"
            'Action Input: {"task": "find facts", "context": "about trazo", '
            '"coworker": "Researcher"}',
            *["Final Answer: report ready"] * 5,
        ],
    )
    task = Task(description="Produce a report on trazo", expected_output="a report")
    return Crew(
        agents=[worker],
        tasks=[task],
        process=Process.hierarchical,
        manager_llm=manager_llm,
        verbose=False,
    )


def test_instrument__hierarchical_crew_records_manager_worker_and_delegation() -> None:
    context_init(project="toy-crew-test")
    shipper = _FakeShipper()
    crew = _hierarchical_crew(
        _CountingTool().build(),
        [
            "Thought: I should search\n"
            "Action: web_search\n"
            'Action Input: {"query": "trazo"}',
            *["Final Answer: facts about trazo"] * 5,
        ],
    )

    result = instrument(crew, recorder=Recorder(shipper=shipper)).kickoff()

    assert result.raw == "report ready"
    llm_calls = _events_by_kind(shipper.enqueued, "llm.call")
    assert [e["payload"]["model"] for e in llm_calls] == [
        "fake-manager",
        "fake-worker",
        "fake-worker",
        "fake-manager",
    ]
    assert [
        e["payload"]["tool_name"]
        for e in _events_by_kind(shipper.enqueued, "tool.call")
    ] == ["web_search"]
    # Delegation is a tool in CrewAI, recorded as a message, not a tool.call.
    assert len(_events_by_kind(shipper.enqueued, "agent.message")) == 1
    assert [
        e["payload"]["status"]
        for e in _events_by_kind(shipper.enqueued, "run.finished")
    ] == ["ok"]


def test_instrument__policy_denial_reaches_a_workers_tool_under_a_manager() -> None:
    context_init(project="toy-crew-test")
    shipper = _FakeShipper()
    counting = _CountingTool()
    crew = _hierarchical_crew(
        counting.build(),
        [
            "Thought: I should search\n"
            "Action: web_search\n"
            'Action Input: {"query": "trazo"}',
            *["Final Answer: facts about trazo"] * 5,
        ],
    )
    traced = instrument(
        crew, recorder=Recorder(shipper=shipper), policy_hook=_policy_hook("deny")
    )

    with pytest.raises(PolicyDenied):
        traced.kickoff()

    assert counting.executions == 0
