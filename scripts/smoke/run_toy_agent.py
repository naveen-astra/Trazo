#!/usr/bin/env python3
"""Runs the toy LangGraph agent (sdk/tests/agents/research_assistant.py)
against a live control plane for the Phase 2 smoke checkpoint
(TASKS/PHASE_2.md; scripts/smoke/phase2.sh). Prints the project id used
(a fixed, distinctive name) on stdout so the shell script can query the
run back through the query API by `?project=`.

Run via (from the repo root, with a live control plane reachable at
TRAZO_ENDPOINT):

    uv run --project sdk --extra langgraph python scripts/smoke/run_toy_agent.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "sdk" / "tests"))

import trazo  # noqa: E402
from agents.research_assistant import build_toy_graph, initial_state  # noqa: E402

from trazo.core.runtime import get_recorder  # noqa: E402
from trazo.integrations.langgraph import instrument  # noqa: E402

PROJECT = "phase2-smoke"


def main() -> int:
    endpoint = os.environ.get("TRAZO_ENDPOINT", "http://localhost:8420")
    api_key = os.environ.get("TRAZO_API_KEY", "dev-change-me")

    trazo.init(project=PROJECT, endpoint=endpoint, api_key=api_key)

    graph, _counters = build_toy_graph(latency_seconds=0.0)
    traced = instrument(graph)
    result = traced.invoke(initial_state())
    if result["search_result"] != "results for trazo":
        print(f"unexpected toy agent result: {result}", file=sys.stderr)
        return 1

    get_recorder().shutdown(timeout=10.0)  # flush the shipper before the process exits

    print(PROJECT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
