#!/usr/bin/env python3
"""Run the research-assistant demo end-to-end (TRZ-P3-02).

    uv run --project sdk --extra langgraph --extra demos \\
        python demos/research-assistant/run.py \\
        [--question "..."] [--endpoint http://localhost:8420] [--live]

``--live`` calls a real model instead of the deterministic fixture stub,
and records the exchange to ``cassette.json`` for fixture mode to replay
later (TRZ-P3-04). For zero cost, run a local model with Ollama::

    ollama pull qwen2.5:3b
    TRAZO_DEMO_LLM_BASE_URL=http://localhost:11434/v1 \
    TRAZO_DEMO_LLM_MODEL=qwen2.5:3b \
        uv run --project sdk --extra langgraph --extra demos \
        python demos/research-assistant/run.py --live

Or set ``TRAZO_DEMO_API_KEY``/``OPENAI_API_KEY`` to use OpenAI. CI stays
on the zero-cost fixture path.

Only the SDK's public API is used here (``trazo.init``,
``trazo.integrations.langgraph.instrument``) — IMPLEMENTATION_PLAN.md's
lane table scopes ``demos/`` to that surface, never ``trazo.core``.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import trazo
from trazo.integrations.langgraph import instrument

DEFAULT_QUESTION = "what is trazo"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the research-assistant demo")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument(
        "--endpoint", default=os.environ.get("TRAZO_ENDPOINT", "http://localhost:8420")
    )
    parser.add_argument("--target-iterations", type=int, default=3)
    parser.add_argument(
        "--live",
        action="store_true",
        help="call a real model and record it to cassette.json, instead of "
        "the deterministic fixture stub",
    )
    args = parser.parse_args()

    # Before the demo's own modules load: llm.py reads this at import to
    # label every traced call with the model that will actually answer.
    if args.live:
        os.environ["TRAZO_DEMO_LIVE"] = "1"
    import llm
    from agent import build_graph, initial_state

    llm.set_live_mode(args.live)

    trazo.init(
        project="research-assistant",
        endpoint=args.endpoint,
        api_key=os.environ.get("TRAZO_API_KEY", "dev-change-me"),
    )

    graph = build_graph(target_iterations=args.target_iterations)
    traced = instrument(graph)
    try:
        result = traced.invoke(initial_state(args.question))
        print(result["answer"])
        print(f"TRAZO_RUN_ID={traced.last_run_id}")
    finally:
        # atexit alone is not reliable for a short-lived process — see
        # trazo.shutdown()'s docstring (found the hard way, running this
        # demo: most events were still queued when the process exited a
        # few hundred ms after the graph finished). Default timeout, not a
        # short explicit one: against an unreachable endpoint each failed
        # POST attempt can itself take several seconds, and one flush
        # cycle can need two of them.
        trazo.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
