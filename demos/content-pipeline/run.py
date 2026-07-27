#!/usr/bin/env python3
"""Run the content-pipeline demo end-to-end (TRZ-P3-03).

    uv run --project sdk --extra crewai python demos/content-pipeline/run.py \\
        [--endpoint http://localhost:8420]

Only the SDK's public API is used here (``trazo.init``,
``trazo.integrations.crewai.instrument``, ``trazo.shutdown``) —
IMPLEMENTATION_PLAN.md's lane table scopes ``demos/`` to that surface,
never ``trazo.core`` (see the research-assistant demo's README for why
the explicit ``trazo.shutdown()`` call is required, not optional).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crew import build_crew

import trazo
from trazo.integrations.crewai import instrument


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the content-pipeline demo")
    parser.add_argument(
        "--endpoint", default=os.environ.get("TRAZO_ENDPOINT", "http://localhost:8420")
    )
    args = parser.parse_args()

    trazo.init(
        project="content-pipeline",
        endpoint=args.endpoint,
        api_key=os.environ.get("TRAZO_API_KEY", "dev-change-me"),
    )

    crew = build_crew()
    traced = instrument(crew)
    try:
        result = traced.kickoff()
        print(result.raw)
    finally:
        # Default timeout, not a short explicit one: this demo is what
        # found the reliability gap that set the default (see
        # trazo.shutdown()'s docstring) — 10s wasn't always enough,
        # losing this run's largest batch when shutdown()'s join timed
        # out mid-POST, silently killing the daemon Shipper thread.
        trazo.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
