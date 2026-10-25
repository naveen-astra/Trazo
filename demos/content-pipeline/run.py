#!/usr/bin/env python3
"""Run the content-pipeline demo end-to-end (TRZ-P3-03).

    uv run --project sdk --extra crewai python demos/content-pipeline/run.py \\
        [--endpoint http://localhost:8420] [--live]

``--live`` calls a real model (OpenAI with ``TRAZO_DEMO_API_KEY`` or
``OPENAI_API_KEY``, or a free local one: set ``TRAZO_DEMO_LLM_BASE_URL``
and ``TRAZO_DEMO_LLM_MODEL`` as ``demos/_shared/README.md`` shows)
instead of the deterministic fixture script, and
records the exchange to ``cassette.json`` for fixture mode to replay
later (TRZ-P3-04) — used by the nightly corpus job (TRZ-P3-05), not by
CI, which stays zero-cost on the default fixture path.

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

import trazo
from trazo.integrations.crewai import instrument


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the content-pipeline demo")
    parser.add_argument(
        "--endpoint", default=os.environ.get("TRAZO_ENDPOINT", "http://localhost:8420")
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="call a real model and record it to cassette.json, instead of "
        "the deterministic fixture script",
    )
    args = parser.parse_args()

    # Before the demo's own modules load: llm.py reads this at import to
    # label every traced call with the model that will actually answer.
    if args.live:
        os.environ["TRAZO_DEMO_LIVE"] = "1"
    import llm
    from crew import build_crew

    llm.set_live_mode(args.live)

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
        print(f"TRAZO_RUN_ID={traced.last_run_id}")
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
