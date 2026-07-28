#!/usr/bin/env python3
"""Append one live demo run to the corpus index (TRZ-P3-05).

    python benchmark/corpus/archive_run.py \\
        --project research-assistant --framework langgraph --run-id 01H...

Appends ``{run_id, project, framework, recorded_at}`` to
``benchmark/corpus/index.json`` (a flat JSON array, created if missing)
and writes it back sorted by ``recorded_at`` — the nightly corpus job's
own durable record of "N runs accumulated" (the task's DoD), independent
of whether the events those runs emitted are still retrievable from
whatever control plane ingested them at the time.

Deliberately stdlib-only: this runs in CI right after each demo's `--live`
invocation, with no guarantee the SDK's own venv is still active.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

INDEX_PATH = Path(__file__).resolve().parent / "index.json"


def append_entry(
    index_path: Path, *, run_id: str, project: str, framework: str
) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    if index_path.exists():
        entries = json.loads(index_path.read_text(encoding="utf-8"))

    entries.append(
        {
            "run_id": run_id,
            "project": project,
            "framework": framework,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    entries.sort(key=lambda e: e["recorded_at"])

    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--framework", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--index-path", type=Path, default=INDEX_PATH)
    args = parser.parse_args()

    entries = append_entry(
        args.index_path,
        run_id=args.run_id,
        project=args.project,
        framework=args.framework,
    )
    label = f"{args.project}/{args.framework}"
    print(f"archived {args.run_id} ({label}); {len(entries)} total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
