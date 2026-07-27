"""The research-assistant demo's LLM calls (TRZ-P3-02).

Deterministic by default (``FixtureLLM``) — TRZ-P3-02's own DoD wants
"deterministic-ish fixture inputs", and TRZ-P3-04's live-mode flag (a real
provider call, gated behind an API key) is a later, additive task; this
module is written so plugging one in later doesn't change any node code
(nodes only ever call the four ``ask_*`` functions below).

Every call goes through the SDK's public ``@trace_llm`` escape hatch, so
each of these deterministic decisions is still recorded as a real
``llm.call`` event with a fingerprint — exactly as if a real model made
the call, since ``@trace_llm`` doesn't know or care how ``fn`` produced
its answer.
"""

from __future__ import annotations

from trazo import trace_llm

MODEL = "fixture-v1"

SUB_TOPICS = ["overview", "architecture", "reliability"]


@trace_llm(provider="fixture", model=MODEL)
def ask_plan(question: str, queries_done: list[str]) -> dict[str, object]:
    """Decide the next search query: rotate through SUB_TOPICS in order."""
    next_topic = SUB_TOPICS[len(queries_done) % len(SUB_TOPICS)]
    query = f"{question} {next_topic}"
    return {
        "response": query,
        "tokens_in": len(question.split()),
        "tokens_out": len(query.split()),
    }


@trace_llm(provider="fixture", model=MODEL)
def ask_synthesize(
    question: str, search_result: str, retrieved: list[str]
) -> dict[str, object]:
    """Combine a fresh search result with related prior findings into one
    finding sentence."""
    context = f" (related: {'; '.join(retrieved)})" if retrieved else ""
    response = f"On '{question}': {search_result}{context}"
    return {
        "response": response,
        "tokens_in": len(search_result.split()),
        "tokens_out": len(response.split()),
    }


@trace_llm(provider="fixture", model=MODEL)
def ask_evaluate(iteration: int, target_iterations: int) -> dict[str, object]:
    """Decide whether enough findings have been gathered."""
    decision = "continue" if iteration < target_iterations else "finalize"
    return {"response": decision, "tokens_in": 2, "tokens_out": 1}


@trace_llm(provider="fixture", model=MODEL)
def ask_finalize(
    question: str, findings: list[str], sources_consulted: float
) -> dict[str, object]:
    """Compose the final answer from every finding gathered so far."""
    response = (
        f"Answer to '{question}' (from {int(sources_consulted)} sources): "
        + " ".join(findings)
    )
    return {
        "response": response,
        "tokens_in": sum(len(f.split()) for f in findings),
        "tokens_out": len(response.split()),
    }
