"""Research-assistant demo agent (TRZ-P3-02, LangGraph): plan -> search ->
retrieve -> synthesize -> evaluate, looping until enough findings are
gathered, then finalize.

Realism bar (TASKS/PHASE_3.md's Phase 3 checkpoint): with the default
``target_iterations=3``, one run produces 5 nodes x 3 iterations + 1
finalize = 16 steps, 5 tool calls (3x web_search, 1x fetch_document, 1x
calculator), 6 memory events (3x read, 3x write), and every node name
becomes a distinct ``agent_id`` (TRZ-P2-04's LangGraph adapter already
scopes each node under its own name) — comfortably over "≥15 steps, ≥2
agents/roles, ≥5 tool calls, memory events present".
"""

from __future__ import annotations

from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from llm import ask_evaluate, ask_finalize, ask_plan, ask_synthesize
from memory import VectorMemory
from tools import calculator, fetch_document, web_search


class ResearchState(TypedDict):
    question: str
    queries_done: list[str]
    findings: list[str]
    pending_query: str
    pending_search_result: str
    pending_retrieved: list[str]
    iteration: int
    decision: str
    answer: str


def build_graph(*, target_iterations: int = 3) -> CompiledStateGraph:
    """Build one fresh graph + its own vector memory. Fresh per call (not
    a module-level singleton) so repeated demo/benchmark runs never share
    memory state, matching the toy-agent pattern from Phase 2."""
    memory = VectorMemory(namespace=f"research-assistant-{id(object())}")

    def plan(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
        query = ask_plan(state["question"], state["queries_done"])["response"]
        return {"pending_query": query, "queries_done": [*state["queries_done"], query]}

    def search(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
        result = web_search(state["pending_query"])
        if state["iteration"] == 0:
            fetch_document("sdk-md")  # a second, distinct tool for realism
        return {"pending_search_result": result}

    def retrieve(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
        retrieved = memory.query(state["question"], k=2)
        return {"pending_retrieved": retrieved}

    def synthesize(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
        finding = ask_synthesize(
            state["question"],
            state["pending_search_result"],
            state["pending_retrieved"],
        )["response"]
        memory.save(key_or_ns="finding", value=finding)
        return {"findings": [*state["findings"], finding]}

    def evaluate(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
        decision = ask_evaluate(state["iteration"] + 1, target_iterations)["response"]
        return {"iteration": state["iteration"] + 1, "decision": decision}

    def route_after_evaluate(state: ResearchState) -> str:
        return "plan" if state["decision"] == "continue" else "finalize"

    def finalize(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
        sources_consulted = calculator(f"{len(state['queries_done'])} + 1")
        answer = ask_finalize(state["question"], state["findings"], sources_consulted)[
            "response"
        ]
        return {"answer": answer}

    graph = StateGraph(ResearchState)
    graph.add_node("plan", plan)
    graph.add_node("search", search)
    graph.add_node("retrieve", retrieve)
    graph.add_node("synthesize", synthesize)
    graph.add_node("evaluate", evaluate)
    graph.add_node("finalize", finalize)

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "search")
    graph.add_edge("search", "retrieve")
    graph.add_edge("retrieve", "synthesize")
    graph.add_edge("synthesize", "evaluate")
    graph.add_conditional_edges(
        "evaluate", route_after_evaluate, {"plan": "plan", "finalize": "finalize"}
    )
    graph.add_edge("finalize", END)

    return graph.compile()


def initial_state(question: str) -> ResearchState:
    return {
        "question": question,
        "queries_done": [],
        "findings": [],
        "pending_query": "",
        "pending_search_result": "",
        "pending_retrieved": [],
        "iteration": 0,
        "decision": "continue",
        "answer": "",
    }
