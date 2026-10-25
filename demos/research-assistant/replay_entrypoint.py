#!/usr/bin/env python3
"""Replay entrypoint for research-assistant (TRZ-P4-07's fidelity
harness). Run in its own process — never imported alongside
content-pipeline's same-named ``llm``/``agent`` modules in one
interpreter, which would collide in ``sys.modules``.

    uv run --project sdk --extra langgraph --extra demos \
        python demos/research-assistant/replay_entrypoint.py <run_id> \
        [--mode verify|strict|lenient] [--step N] \
        [--endpoint http://localhost:8420] [--json]

The default ``--mode verify`` prints ``trazo verify``'s fidelity report;
``strict``/``lenient`` re-drive like ``trazo replay``. Both delegate to
``trazo.cli.replay`` directly rather than shelling out to the ``trazo``
console script, so this stays one process. A run recorded live replays
with no extra settings: its model labels are read from the recording
(``demos/_shared/replay_cli.py``).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_shared"))

from replay_cli import main as replay_main

from trazo import replay
from trazo.integrations.langgraph import instrument


def _register() -> None:
    # Imported only now, after the recorded labels are adopted: llm.py
    # bakes them into its @trace_llm decorators at import.
    from agent import build_graph

    @replay.entrypoint(framework="langgraph")
    def _replay_research_assistant(entry_input: object) -> object:
        graph = build_graph()
        traced = instrument(graph)
        return traced.invoke(entry_input)  # type: ignore[arg-type]


if __name__ == "__main__":
    sys.exit(replay_main(description=__doc__, register=_register))
