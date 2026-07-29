#!/usr/bin/env python3
"""Generate the labeled failure corpus (TRZ-P5-02, AI_DEBUGGER.md §4).

    python benchmark/corpus/generate_failure_corpus.py \\
        [--per-class 25] [--clean 50] [--index-path failure_index.json]

Runs each demo's ``chaos_run.py`` N times per fault class (loop/budget/
thrash/drift) plus N clean runs via its normal ``run.py``, converts each
run's spool straight into a cached replay bundle (``benchmark/fidelity/
spool_to_bundle.py`` — no control plane needed, same trick the fidelity
harness and its own integration check use), and appends one manifest
entry per run to ``failure_index.json``: run_id, project, framework,
label (fault class or "clean"), recorded_at.

Only the manifest is committed — bundle payloads stay in
``_runs/.trazo/cache/`` (gitignored, local only): this task's own DoD is
"manifests committed, run refs not payloads." Re-running the offline
scorer (TRZ-P5-05) against this corpus later in the same environment
needs those cached bundles to still be on disk; regenerating them
elsewhere just means running this script again.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKDIR = Path(__file__).resolve().parent / "_runs"
_DEFAULT_INDEX_PATH = Path(__file__).resolve().parent / "failure_index.json"

sys.path.insert(0, str(_REPO_ROOT / "benchmark" / "fidelity"))
from spool_to_bundle import NoRunStartedError, write_bundle_cache  # noqa: E402

_RUN_ID_PATTERN = re.compile(r"^TRAZO_RUN_ID=(.+)$", re.MULTILINE)
_UNREACHABLE_ENDPOINT = "http://127.0.0.1:1"

FAULT_CLASSES = ("loop", "budget", "thrash", "drift")

_SDK_PATH = str(_REPO_ROOT / "sdk")

_DEMOS: dict[str, dict[str, Any]] = {
    "research-assistant": {
        "framework": "langgraph",
        "clean_command": [
            "uv",
            "run",
            "--project",
            _SDK_PATH,
            "--extra",
            "langgraph",
            "--extra",
            "demos",
            "python",
            str(_REPO_ROOT / "demos" / "research-assistant" / "run.py"),
        ],
        "chaos_command": [
            "uv",
            "run",
            "--project",
            _SDK_PATH,
            "--extra",
            "langgraph",
            "--extra",
            "demos",
            "python",
            str(_REPO_ROOT / "demos" / "research-assistant" / "chaos_run.py"),
        ],
    },
    "content-pipeline": {
        "framework": "crewai",
        "clean_command": [
            "uv",
            "run",
            "--project",
            _SDK_PATH,
            "--extra",
            "crewai",
            "python",
            str(_REPO_ROOT / "demos" / "content-pipeline" / "run.py"),
        ],
        "chaos_command": [
            "uv",
            "run",
            "--project",
            _SDK_PATH,
            "--extra",
            "crewai",
            "python",
            str(_REPO_ROOT / "demos" / "content-pipeline" / "chaos_run.py"),
        ],
    },
}


def _run_once(command: list[str]) -> str | None:
    result = subprocess.run(
        [*command, "--endpoint", _UNREACHABLE_ENDPOINT],
        capture_output=True,
        text=True,
        cwd=_WORKDIR,
        check=False,
    )
    match = _RUN_ID_PATTERN.search(result.stdout)
    if not match:
        print(
            f"generate_failure_corpus: no TRAZO_RUN_ID in output of {command}",
            file=sys.stderr,
        )
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return None
    run_id = match.group(1)

    try:
        write_bundle_cache(
            spool_dir=_WORKDIR / ".trazo" / "spool",
            cache_dir=_WORKDIR / ".trazo" / "cache",
            run_id=run_id,
        )
    except NoRunStartedError as exc:
        print(f"generate_failure_corpus: {exc}", file=sys.stderr)
        return None
    return run_id


def _load_entries(index_path: Path) -> list[dict[str, Any]]:
    if index_path.exists():
        return list(json.loads(index_path.read_text(encoding="utf-8")))
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-class", type=int, default=25)
    parser.add_argument("--clean", type=int, default=50)
    parser.add_argument("--index-path", type=Path, default=_DEFAULT_INDEX_PATH)
    args = parser.parse_args()

    _WORKDIR.mkdir(parents=True, exist_ok=True)
    entries = _load_entries(args.index_path)

    for project, config in _DEMOS.items():
        for _ in range(args.clean):
            run_id = _run_once(config["clean_command"])
            if run_id is not None:
                entries.append(
                    {
                        "run_id": run_id,
                        "project": project,
                        "framework": config["framework"],
                        "label": "clean",
                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
        for fault in FAULT_CLASSES:
            for _ in range(args.per_class):
                run_id = _run_once([*config["chaos_command"], fault])
                if run_id is not None:
                    entries.append(
                        {
                            "run_id": run_id,
                            "project": project,
                            "framework": config["framework"],
                            "label": fault,
                            "recorded_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )

    args.index_path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(entries)} entries to {args.index_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
