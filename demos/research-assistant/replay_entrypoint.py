#!/usr/bin/env python3
"""Replay entrypoint for research-assistant (TRZ-P4-07's fidelity
harness). Run in its own process — never imported alongside
content-pipeline's same-named ``llm``/``agent`` modules in one
interpreter, which would collide in ``sys.modules``.

    uv run --project sdk --extra langgraph --extra demos \\
        python demos/research-assistant/replay_entrypoint.py <run_id> \\
        [--endpoint http://localhost:8420] [--json]

Prints ``trazo verify``'s report to stdout (delegates to
``trazo.cli.replay.run_verify`` directly rather than shelling out to the
``trazo`` console script, so this stays one process).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import build_graph

from trazo import replay
from trazo.cli.replay import run_verify
from trazo.integrations.langgraph import instrument


@replay.entrypoint(framework="langgraph")
def _replay_research_assistant(entry_input: object) -> object:
    graph = build_graph()
    traced = instrument(graph)
    return traced.invoke(entry_input)  # type: ignore[arg-type]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument(
        "--endpoint", default=os.environ.get("TRAZO_ENDPOINT", "http://localhost:8420")
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    return run_verify(
        args.run_id,
        endpoint=args.endpoint,
        api_key=os.environ.get("TRAZO_API_KEY"),
        as_json=args.as_json,
    )


if __name__ == "__main__":
    sys.exit(main())
