#!/usr/bin/env python3
"""Replay entrypoint for content-pipeline (TRZ-P4-07's fidelity harness).
Run in its own process — never imported alongside research-assistant's
same-named ``llm`` module in one interpreter, which would collide in
``sys.modules``.

    uv run --project sdk --extra crewai \\
        python demos/content-pipeline/replay_entrypoint.py <run_id> \\
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
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crew import build_crew

from trazo import replay
from trazo.cli.replay import run_verify
from trazo.integrations.crewai import instrument


@replay.entrypoint(framework="crewai")
def _replay_content_pipeline(entry_input: Any) -> object:
    crew = build_crew()
    traced = instrument(crew)
    return traced.kickoff(inputs=entry_input or {})


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
