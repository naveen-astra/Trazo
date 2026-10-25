#!/usr/bin/env python3
"""Replay entrypoint for content-pipeline (TRZ-P4-07's fidelity harness).
Run in its own process — never imported alongside research-assistant's
same-named ``llm`` module in one interpreter, which would collide in
``sys.modules``.

    uv run --project sdk --extra crewai \
        python demos/content-pipeline/replay_entrypoint.py <run_id> \
        [--mode verify|strict|lenient] [--step N] \
        [--endpoint http://localhost:8420] [--json]

The default ``--mode verify`` prints ``trazo verify``'s fidelity report;
``strict``/``lenient`` re-drive like ``trazo replay``. Both delegate to
``trazo.cli.replay`` directly rather than shelling out to the ``trazo``
console script, so this stays one process. The recorded run's model
label is adopted automatically (``demos/_shared/replay_cli.py``). CrewAI
really calls the LLM during replay, answered from the cassette, so a run
recorded live with ``TRAZO_DEMO_CASSETTE`` set must be replayed with the
same ``TRAZO_DEMO_CASSETTE``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_shared"))

from replay_cli import main as replay_main

from trazo import replay
from trazo.integrations.crewai import instrument


def _register() -> None:
    # Imported only now, after the recorded label is adopted: llm.py reads
    # it at import.
    from crew import build_crew

    @replay.entrypoint(framework="crewai")
    def _replay_content_pipeline(entry_input: Any) -> object:
        crew = build_crew()
        traced = instrument(crew)
        return traced.kickoff(inputs=entry_input or {})


if __name__ == "__main__":
    sys.exit(replay_main(description=__doc__, register=_register))
