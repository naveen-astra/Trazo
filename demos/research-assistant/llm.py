"""The research-assistant demo's LLM calls (TRZ-P3-02, live mode TRZ-P3-04).

Deterministic by default (the fixture stub each ``ask_*`` falls back to)
— TRZ-P3-02's own DoD wants "deterministic-ish fixture inputs" — with an
opt-in ``--live`` mode (``set_live_mode(True)``, called from ``run.py``)
that calls a real model instead and records the exchange to a cassette
file (``cassette.json``, VCR-style). Nodes only ever call the four
``ask_*`` functions below — the fixture/cassette/live switch lives
entirely inside this module, so plugging live mode in never touched
``agent.py``.

Precedence, simplest case first:

- fixture mode (default): cassette hit -> replay it; cassette miss ->
  deterministic rule-based stub. Works today, with no cassette recorded
  yet, exactly as it did before TRZ-P3-04.
- live mode (``--live``): always calls the real model and records the
  result, regardless of any existing cassette entry — a nightly corpus
  run (TRZ-P3-05) needs fresh completions each time, not a replay of
  the first night's.

Every call goes through the SDK's public ``@trace_llm`` escape hatch, so
each decision is recorded as a real ``llm.call`` event with a
fingerprint — exactly as if a real model made the call every time,
since ``@trace_llm`` doesn't know or care how ``fn`` produced its answer.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_shared"))

from cassette import Cassette, request_key
from live_llm import complete as live_complete

from trazo import trace_llm

MODEL = "fixture-v1"
LIVE_MODEL = "gpt-4o-mini"

SUB_TOPICS = ["overview", "architecture", "reliability"]

_CASSETTE_PATH = Path(__file__).resolve().parent / "cassette.json"
_cassette = Cassette(_CASSETTE_PATH)
_live_mode = False


def set_live_mode(live: bool) -> None:
    """Switch every ``ask_*`` function between fixture and live mode.
    Called once by ``run.py`` before the graph runs — never toggled
    mid-run."""
    global _live_mode
    _live_mode = live


def _resolve(name: str, kwargs: dict[str, object], *, prompt: str) -> dict[str, object]:
    key = request_key(name, kwargs)
    if not _live_mode:
        cached = _cassette.get(key)
        if cached is not None:
            return cached
        return _fixture(name, kwargs)

    result = live_complete(prompt, model=LIVE_MODEL)
    _cassette.put(key, result)
    _cassette.save()
    return result


def _fixture(name: str, kwargs: dict[str, object]) -> dict[str, object]:
    if name == "ask_plan":
        question = str(kwargs["question"])
        queries_done = list(kwargs["queries_done"])  # type: ignore[arg-type]
        next_topic = SUB_TOPICS[len(queries_done) % len(SUB_TOPICS)]
        query = f"{question} {next_topic}"
        return {
            "response": query,
            "tokens_in": len(question.split()),
            "tokens_out": len(query.split()),
        }
    if name == "ask_synthesize":
        question = str(kwargs["question"])
        search_result = str(kwargs["search_result"])
        retrieved = list(kwargs["retrieved"])  # type: ignore[arg-type]
        context = f" (related: {'; '.join(retrieved)})" if retrieved else ""
        response = f"On '{question}': {search_result}{context}"
        return {
            "response": response,
            "tokens_in": len(search_result.split()),
            "tokens_out": len(response.split()),
        }
    if name == "ask_evaluate":
        iteration = int(kwargs["iteration"])  # type: ignore[arg-type]
        target_iterations = int(kwargs["target_iterations"])  # type: ignore[arg-type]
        decision = "continue" if iteration < target_iterations else "finalize"
        return {"response": decision, "tokens_in": 2, "tokens_out": 1}
    if name == "ask_finalize":
        question = str(kwargs["question"])
        findings = list(kwargs["findings"])  # type: ignore[arg-type]
        sources_consulted = float(kwargs["sources_consulted"])  # type: ignore[arg-type]
        response = (
            f"Answer to '{question}' (from {int(sources_consulted)} sources): "
            + " ".join(findings)
        )
        return {
            "response": response,
            "tokens_in": sum(len(f.split()) for f in findings),
            "tokens_out": len(response.split()),
        }
    raise ValueError(f"no fixture for {name}")  # pragma: no cover — defensive


@trace_llm(provider="fixture", model=MODEL)
def ask_plan(question: str, queries_done: list[str]) -> dict[str, object]:
    """Decide the next search query: rotate through SUB_TOPICS in order
    (fixture) or ask a real model (live)."""
    kwargs = {"question": question, "queries_done": queries_done}
    prompt = (
        f"Research question: '{question}'. Topics already searched: "
        f"{queries_done}. What is the next search query to run? Respond "
        "with only the query text."
    )
    return _resolve("ask_plan", kwargs, prompt=prompt)


@trace_llm(provider="fixture", model=MODEL)
def ask_synthesize(
    question: str, search_result: str, retrieved: list[str]
) -> dict[str, object]:
    """Combine a fresh search result with related prior findings into one
    finding sentence."""
    kwargs = {
        "question": question,
        "search_result": search_result,
        "retrieved": retrieved,
    }
    prompt = (
        f"Question: '{question}'. New search result: '{search_result}'. "
        f"Related prior findings: {retrieved}. Write one sentence "
        "combining the new result with any relevant prior findings."
    )
    return _resolve("ask_synthesize", kwargs, prompt=prompt)


@trace_llm(provider="fixture", model=MODEL)
def ask_evaluate(iteration: int, target_iterations: int) -> dict[str, object]:
    """Decide whether enough findings have been gathered."""
    kwargs = {"iteration": iteration, "target_iterations": target_iterations}
    prompt = (
        f"{iteration} of a target {target_iterations} research iterations "
        "are complete. Respond with exactly one word: 'continue' or "
        "'finalize'."
    )
    return _resolve("ask_evaluate", kwargs, prompt=prompt)


@trace_llm(provider="fixture", model=MODEL)
def ask_finalize(
    question: str, findings: list[str], sources_consulted: float
) -> dict[str, object]:
    """Compose the final answer from every finding gathered so far."""
    kwargs = {
        "question": question,
        "findings": findings,
        "sources_consulted": sources_consulted,
    }
    prompt = (
        f"Question: '{question}'. Findings gathered from "
        f"{int(sources_consulted)} sources: {findings}. Compose a final "
        "answer, citing the number of sources."
    )
    return _resolve("ask_finalize", kwargs, prompt=prompt)
