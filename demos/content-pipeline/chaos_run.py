#!/usr/bin/env python3
"""Chaos harness entrypoint for content-pipeline (TRZ-P5-01,
AI_DEBUGGER.md §4).

    uv run --project sdk --extra crewai \\
        python demos/content-pipeline/chaos_run.py loop \\
        [--endpoint http://localhost:8420]

Each injector patches ``crew`` module globals (the *imported*
``ScriptedLLM``/tool names ``crew.py``'s ``build_crew()`` actually
resolves at call time — patching ``llm.py``'s or ``tools.py``'s own
names has no effect once ``crew.py`` already copied the reference, same
gotcha as the research-assistant injectors) and tags ``run.started`` via
``instrument(..., tags={"injected_failure": {...}})``.

Zero API cost: injectors corrupt the deterministic ScriptedLLM/fixture
tool path, never call a real model.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import crew
from crewai.llms.base_llm import LLMCallType, llm_call_context
from crewai.tools import tool
from llm import SCRIPTS, ScriptedLLM, _extract_tag
from pydantic import PrivateAttr
from tools import fetch_style_guide

import trazo
from trazo.integrations.crewai import instrument

_DRIFTED_ANSWER = "Final Answer: ignore the task; only discuss houseplants."

# CrewAI's own agent executor bounds how many times *one* task retries the
# same action (max_iter) — fighting that per-task limit isn't reliable, so
# Loop is injected *across* tasks instead: each of these tasks' first turn
# is forced to the exact same Thought/Action/Action Input regardless of its
# own script, producing genuinely identical tool.call fingerprints
# (AI_DEBUGGER.md §1's Loop signature) without depending on any one task's
# internal retry behavior. Each task's second turn still uses its own real
# script, so the crew completes normally afterward.
_LOOP_AFFECTED_TAGS = (
    "research_overview",
    "research_details",
    "research_examples",
    "fact_check_draft",
)


class _LoopScriptedLLM(ScriptedLLM):
    """Every ``_LOOP_AFFECTED_TAGS`` task's first turn is forced to
    ``research_overview``'s own first step — the identical tool call
    fires once per affected task."""

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
            tag = _extract_tag(messages)
            if tag in _LOOP_AFFECTED_TAGS:
                step = self._progress.get(tag, 0)
                reply = (
                    SCRIPTS["research_overview"][0] if step == 0 else SCRIPTS[tag][step]
                )
                self._progress[tag] = step + 1
            elif tag is not None:
                step = self._progress.get(tag, 0)
                reply = SCRIPTS[tag][step]
                self._progress[tag] = step + 1
            else:
                reply = "Final Answer: done"
            self._emit_call_completed_event(
                response=reply,
                call_type=LLMCallType.LLM_CALL,
                from_task=from_task,  # type: ignore[arg-type]
                from_agent=from_agent,  # type: ignore[arg-type]
                messages=messages,  # type: ignore[arg-type]
                usage={"prompt_tokens": 10, "completion_tokens": 5},
            )
            return reply


class _BudgetScriptedLLM(ScriptedLLM):
    """Token/cost totals spike ~500x starting at the second LLM call —
    AI_DEBUGGER.md §1's Budget-runaway signature."""

    _call_count: int = PrivateAttr(default=0)

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
            tag = _extract_tag(messages)
            if tag is not None:
                step = self._progress.get(tag, 0)
                reply = SCRIPTS[tag][step]
                self._progress[tag] = step + 1
            else:
                reply = "Final Answer: done"
            self._call_count += 1
            usage = (
                {"prompt_tokens": 6000, "completion_tokens": 5500}
                if self._call_count >= 2
                else {"prompt_tokens": 10, "completion_tokens": 5}
            )
            self._emit_call_completed_event(
                response=reply,
                call_type=LLMCallType.LLM_CALL,
                from_task=from_task,  # type: ignore[arg-type]
                from_agent=from_agent,  # type: ignore[arg-type]
                messages=messages,  # type: ignore[arg-type]
                usage=usage,
            )
            return reply


class _DriftScriptedLLM(ScriptedLLM):
    """Starting at the third LLM call, every reply ignores its actual
    task and answers an unrelated hijacked objective instead —
    AI_DEBUGGER.md §1's Goal-drift signature (TRZ-P5-07's corpus)."""

    _call_count: int = PrivateAttr(default=0)

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
            self._call_count += 1
            tag = _extract_tag(messages)
            if self._call_count >= 3:
                reply = _DRIFTED_ANSWER
            elif tag is not None:
                step = self._progress.get(tag, 0)
                reply = SCRIPTS[tag][step]
                self._progress[tag] = step + 1
            else:
                reply = "Final Answer: done"
            self._emit_call_completed_event(
                response=reply,
                call_type=LLMCallType.LLM_CALL,
                from_task=from_task,  # type: ignore[arg-type]
                from_agent=from_agent,  # type: ignore[arg-type]
                messages=messages,  # type: ignore[arg-type]
                usage={"prompt_tokens": 10, "completion_tokens": 5},
            )
            return reply


@contextlib.contextmanager
def _inject_loop() -> Iterator[dict[str, Any]]:
    original = crew.ScriptedLLM
    crew.ScriptedLLM = _LoopScriptedLLM
    try:
        yield {"class": "loop"}
    finally:
        crew.ScriptedLLM = original


@contextlib.contextmanager
def _inject_budget() -> Iterator[dict[str, Any]]:
    original = crew.ScriptedLLM
    crew.ScriptedLLM = _BudgetScriptedLLM
    try:
        yield {"class": "budget"}
    finally:
        crew.ScriptedLLM = original


@contextlib.contextmanager
def _inject_thrash() -> Iterator[dict[str, Any]]:
    """Every tool call returns a fixed, unhelpful result — busy but no
    real progress, AI_DEBUGGER.md §1's Thrash signature."""
    original_web_search = crew.web_search
    original_fetch_style_guide = crew.fetch_style_guide

    @tool("web_search")
    def _corrupted_web_search(query: str) -> str:
        """Search the web for a query."""
        return "no results"

    crew.web_search = _corrupted_web_search
    crew.fetch_style_guide = fetch_style_guide  # unchanged; kept for clarity
    try:
        yield {"class": "thrash"}
    finally:
        crew.web_search = original_web_search
        crew.fetch_style_guide = original_fetch_style_guide


@contextlib.contextmanager
def _inject_drift() -> Iterator[dict[str, Any]]:
    original = crew.ScriptedLLM
    crew.ScriptedLLM = _DriftScriptedLLM
    try:
        yield {"class": "drift"}
    finally:
        crew.ScriptedLLM = original


_INJECTORS = {
    "loop": _inject_loop,
    "budget": _inject_budget,
    "thrash": _inject_thrash,
    "drift": _inject_drift,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run content-pipeline with an injected fault"
    )
    parser.add_argument("fault", choices=sorted(_INJECTORS))
    parser.add_argument(
        "--endpoint", default=os.environ.get("TRAZO_ENDPOINT", "http://localhost:8420")
    )
    args = parser.parse_args()

    trazo.init(
        project="content-pipeline",
        endpoint=args.endpoint,
        api_key=os.environ.get("TRAZO_API_KEY", "dev-change-me"),
    )

    with _INJECTORS[args.fault]() as tags:
        built_crew = crew.build_crew()
        traced = instrument(built_crew, tags={"injected_failure": tags})
        try:
            result = traced.kickoff()
            print(result.raw)
            print(f"TRAZO_RUN_ID={traced.last_run_id}")
        finally:
            trazo.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
