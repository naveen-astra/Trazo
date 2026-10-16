"""Toy "research assistant" LangGraph agent (Phase 2 checkpoint,
TASKS/PHASE_2.md): a two-node ``plan -> search`` graph, one LLM call and
one tool call, shared by the LangGraph adapter's own integration test
(``test_langgraph_adapter.py``) and the TRZ-P2-09 overhead benchmark
(``benchmark/agent_overhead.py``).

``latency_seconds`` simulates the wall-clock cost of a real LLM/tool call
(network + inference latency). It defaults to 0 for the adapter test,
where only correctness and boundary coverage matter and a real sleep
would just slow the suite down. The overhead benchmark passes a realistic
non-zero value instead — without it, a toy call costs nanoseconds, and
the SDK's fixed per-call overhead (context manager, fingerprint sha256,
ULID generation) would dominate and produce a meaningless ratio (see
``benchmark/overhead.py``'s docstring for the same point about a
trivial baseline function).

LangGraph hands node functions a fully-configured ``CallbackManager`` in
``config["callbacks"]`` (verified empirically) — the plan node drives it
directly with ``on_chat_model_start``/``on_llm_end`` rather than going
through a real chat-model class, since the adapter's callback handler only
cares that those events fire, not who fires them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph


class ToyState(TypedDict):
    messages: list[Any]
    search_result: str


@dataclass
class ToyAgentCounters:
    """Real-call counters, independent of anything the recorder observed —
    the adapter test's boundary-coverage audit compares these against
    recorded events."""

    llm_calls: int = field(default=0)
    tool_calls: int = field(default=0)


def build_toy_graph(
    *, latency_seconds: float = 0.0
) -> tuple[CompiledStateGraph, ToyAgentCounters]:
    """Build one fresh compiled graph + its counters. Fresh per call (not a
    module-level singleton) so concurrent or repeated benchmark iterations
    never share counter state."""
    counters = ToyAgentCounters()

    @tool
    def web_search(query: str) -> str:
        """Search the web for a query."""
        counters.tool_calls += 1
        if latency_seconds:
            time.sleep(latency_seconds)
        return f"results for {query}"

    def _plan_node(state: ToyState, config: RunnableConfig) -> dict[str, Any]:
        counters.llm_calls += 1
        manager = config["callbacks"]
        typed_messages: list[BaseMessage] = list(state["messages"])
        run_managers = manager.on_chat_model_start(
            {"id": ["fake", "ToyChatModel"], "lc": 1, "type": "not_implemented"},
            [typed_messages],
            invocation_params={"model": "fake-model-v1", "temperature": 0.0},
        )
        if latency_seconds:
            time.sleep(latency_seconds)
        reply = "I will search for that."
        response = AIMessage(content=reply)
        result = LLMResult(
            generations=[[ChatGeneration(text=reply, message=response)]],
            llm_output={"token_usage": {"prompt_tokens": 5, "completion_tokens": 3}},
        )
        for run_manager in run_managers:
            run_manager.on_llm_end(result)
        return {"messages": [*state["messages"], response]}

    def _search_node(state: ToyState, config: RunnableConfig) -> dict[str, Any]:
        result = web_search.invoke({"query": "trazo"}, config=config)
        return {"search_result": result}

    graph = StateGraph(ToyState)
    graph.add_node("plan", _plan_node)
    graph.add_node("search", _search_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "search")
    graph.add_edge("search", END)
    return graph.compile(), counters


def initial_state() -> ToyState:
    return {
        "messages": [HumanMessage(content="find me something")],
        "search_result": "",
    }
