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

from crewai import Agent, Crew, Process, Task
from crewai.llms.base_llm import BaseLLM, LLMCallType, llm_call_context
from pydantic import Field

from trazo.core.context import init as context_init
from trazo.core.recorder import Recorder
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
