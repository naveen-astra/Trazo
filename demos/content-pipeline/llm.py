"""The content-pipeline demo's LLM calls (TRZ-P3-03, live mode TRZ-P3-04):
deterministic by default, same rationale as the research-assistant demo's
``llm.py`` — TRZ-P3-02's "deterministic-ish fixture inputs" DoD and
TRZ-P3-04's "zero API cost" constraint apply to every demo, not just the
first one.

Unlike the LangGraph demo (one ``@trace_llm``-wrapped function per node),
CrewAI's ``Agent`` takes a single ``llm`` object whose ``call()`` method
fires for *every* task the agent executes — so ``ScriptedLLM`` looks up
its response by a unique tag embedded in the task's own ``description``
(CrewAI's prompt template includes it verbatim as "Current Task:
{description}", confirmed empirically), rather than tracking a linear
per-instance step counter the way the LangGraph demo's toy fixture did.

Each entry in ``SCRIPTS`` is one task's list of ReAct-format responses
(``crewai.agents.parser``'s documented format) — one entry for a plain
answer, two for a task that calls a tool (or delegates) before answering.

Live mode (``set_live_mode(True)``, called from ``run.py``'s ``--live``)
forwards the *entire* ReAct-format ``messages`` CrewAI built (system
prompt + task + history-so-far) to a real model and records the exchange
to ``cassette.json``, keyed by that exact message content — not by tag —
because live mode's whole point is CrewAI driving the conversation
itself (thought/action/observation loop) rather than replaying a fixed
per-tag script. Fixture-mode replay works turn by turn for the same
reason a VCR cassette always does: as long as it keeps replaying the
recorded responses verbatim, each next turn's prompt prefix is
byte-identical to what was recorded, so the next cassette lookup keeps
hitting.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_shared"))

from cassette import Cassette, request_key
from crewai.llms.base_llm import BaseLLM, LLMCallType, llm_call_context
from live_llm import complete as live_complete
from live_llm import configured_model, trace_labels
from pydantic import PrivateAttr

# Decided at import, like the research assistant's: the model label enters
# every llm.call fingerprint (CrewAI's listener infers the provider from
# it), so recording and replay must agree on it. run.py sets
# TRAZO_DEMO_LIVE for --live before importing this module, and
# replay_entrypoint.py adopts the recorded run's label.
LIVE = os.environ.get("TRAZO_DEMO_LIVE") == "1"
_, TRACE_MODEL = trace_labels(live=LIVE)

# Overridable so a live run can record somewhere other than the demo's own
# cassette, which fixture mode (and therefore CI) replays. Replaying a
# live run needs the same path: CrewAI really calls the LLM during replay,
# and fixture mode answers from this cassette.
_CASSETTE_PATH = Path(
    os.environ.get(
        "TRAZO_DEMO_CASSETTE", Path(__file__).resolve().parent / "cassette.json"
    )
)
_cassette = Cassette(_CASSETTE_PATH)
_live_mode = LIVE


def set_live_mode(live: bool) -> None:
    """Switch ``ScriptedLLM.call()`` between fixture and live mode.
    Called once by ``run.py`` before the crew runs — never toggled
    mid-run."""
    global _live_mode
    _live_mode = live


_TAG_PATTERN = re.compile(r"\[(\w+)\]")

SCRIPTS: dict[str, list[str]] = {
    "research_overview": [
        "Thought: I should search\n"
        "Action: web_search\n"
        'Action Input: {"query": "trazo overview"}',
        "Final Answer: Trazo records agent runs as a sequence of typed "
        "events with fingerprints.",
    ],
    "research_details": [
        "Thought: I should search\n"
        "Action: web_search\n"
        'Action Input: {"query": "trazo details"}',
        "Final Answer: Every boundary-critical event carries a sha256 "
        "fingerprint of its normalized inputs.",
    ],
    "research_examples": [
        "Thought: I should search\n"
        "Action: web_search\n"
        'Action Input: {"query": "trazo examples"}',
        "Final Answer: instrument(crew).kickoff(...) traces a CrewAI run "
        "with zero code changes.",
    ],
    "fact_check_draft": [
        "Thought: I should verify\n"
        "Action: web_search\n"
        'Action Input: {"query": "trazo details"}',
        "Final Answer: the draft's claims match the source material.",
    ],
    "outline": ["Final Answer: 1) overview 2) details 3) examples 4) conclusion"],
    "draft_introduction": [
        "Final Answer: Trazo is an observability, replay, and governance SDK."
    ],
    "draft_body": [
        "Final Answer: Trazo captures every run/step/llm/tool/memory "
        "boundary as a typed event."
    ],
    "draft_conclusion": [
        "Final Answer: Trazo turns opaque agent runs into an inspectable, "
        "replayable trace."
    ],
    "delegate_to_researcher_for_gap": [
        "Thought: I need one more fact from the researcher\n"
        "Action: Delegate work to coworker\n"
        'Action Input: {"task": "confirm the fingerprint claim", '
        '"context": "drafting the body section", "coworker": "Researcher"}',
        "Final Answer: incorporated the researcher's confirmation into the draft.",
    ],
    "self_review": ["Final Answer: draft reads consistently end to end."],
    "edit_grammar": ["Final Answer: no grammar issues found."],
    "edit_clarity": ["Final Answer: clarified two sentences in the body section."],
    "edit_consistency": ["Final Answer: terminology is consistent throughout."],
    "proofread": [
        "Thought: I should check length\n"
        "Action: word_count\n"
        'Action Input: {"text": "the final draft"}',
        "Final Answer: length is within the target range.",
    ],
    "finalize_formatting": ["Final Answer: formatting matches the house style guide."],
}


_DELEGATED_TASK_FALLBACK = (
    "Final Answer: confirmed — the fingerprint claim matches the source material."
)


def _extract_tag(messages: object) -> str | None:
    """Find which of ``SCRIPTS``' declared tasks this call belongs to, or
    ``None`` if it's a delegated ad-hoc task (CrewAI's delegation tool
    builds a brand-new task description from whatever the delegating
    agent's ``Action Input`` says, e.g. "confirm the fingerprint claim" —
    it was never one of this module's own 15 declared ``Task`` objects,
    so it has no ``[tag]`` and no script). CrewAI's system prompt also
    lists tool names in brackets (e.g. "only one name of [web_search]"),
    so a bare "first ``[...]`` in the whole prompt" search is ambiguous —
    only ``Current Task:`` onward is searched."""
    text = str(messages)
    task_section = text.rsplit("Current Task:", 1)[-1]
    for match in _TAG_PATTERN.finditer(task_section):
        if match.group(1) in SCRIPTS:
            return match.group(1)
    return None


class ScriptedLLM(BaseLLM):
    """Fake LLM driving crewai_event_bus exactly like a real provider's
    ``call()`` would (``llm_call_context()`` + the same event-emission
    helpers ``BaseLLM`` gives every subclass), returning each task's
    canned ReAct-format response in order."""

    model: str = TRACE_MODEL
    _progress: dict[str, int] = PrivateAttr(default_factory=dict)

    def call(
        self,
        messages: object,
        tools: object = None,
        callbacks: object = None,
        available_functions: object = None,
        from_task: object = None,
        from_agent: object = None,
        response_model: object = None,
    ) -> str:
        with llm_call_context():
            self._emit_call_started_event(
                messages=messages,  # type: ignore[arg-type]
                tools=tools,  # type: ignore[arg-type]
                callbacks=callbacks,  # type: ignore[arg-type]
                available_functions=available_functions,  # type: ignore[arg-type]
                from_task=from_task,  # type: ignore[arg-type]
                from_agent=from_agent,  # type: ignore[arg-type]
            )
            key = request_key("crewai_call", {"messages": str(messages)})
            if _live_mode:
                result = live_complete(str(messages), model=configured_model())
                reply = str(result["response"])
                usage = {
                    "prompt_tokens": result["tokens_in"],
                    "completion_tokens": result["tokens_out"],
                }
                _cassette.put(key, result)
                _cassette.save()
            else:
                cached = _cassette.get(key)
                if cached is not None:
                    reply = str(cached["response"])
                    usage = {
                        "prompt_tokens": cached["tokens_in"],
                        "completion_tokens": cached["tokens_out"],
                    }
                else:
                    tag = _extract_tag(messages)
                    if tag is None:
                        reply = _DELEGATED_TASK_FALLBACK
                    else:
                        step = self._progress.get(tag, 0)
                        reply = SCRIPTS[tag][step]
                        self._progress[tag] = step + 1
                    usage = {"prompt_tokens": 10, "completion_tokens": 5}
            self._emit_call_completed_event(
                response=reply,
                call_type=LLMCallType.LLM_CALL,
                from_task=from_task,  # type: ignore[arg-type]
                from_agent=from_agent,  # type: ignore[arg-type]
                messages=messages,  # type: ignore[arg-type]
                usage=usage,
            )
            return reply
