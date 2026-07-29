#!/usr/bin/env python3
"""Replay integration check (TRZ-P4-08): runs one demo for real (fixture
mode, unreachable endpoint — Shipper spools instead of failing), converts
its spool straight into a replay bundle (``benchmark/fidelity/
spool_to_bundle.py`` — no control plane, no Docker needed), replays it,
and asserts zero divergence + full fidelity.

This is what actually proves the replay engine works against both real
framework adapters end to end, not just the Substituter's own unit
tests — and it needs no live LLM call, so it runs green in ordinary CI.

    python scripts/replay/verify_fidelity.py research-assistant
    python scripts/replay/verify_fidelity.py content-pipeline
    python scripts/replay/verify_fidelity.py all
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "benchmark" / "fidelity"))

from spool_to_bundle import write_bundle_cache  # noqa: E402

_UNREACHABLE_ENDPOINT = "http://127.0.0.1:1"
_RUN_ID_PATTERN = re.compile(r"^TRAZO_RUN_ID=(.+)$", re.MULTILINE)

_DEMOS: dict[str, dict[str, list[str]]] = {
    "research-assistant": {
        "run_command": [
            "uv",
            "run",
            "--project",
            str(_REPO_ROOT / "sdk"),
            "--extra",
            "langgraph",
            "--extra",
            "demos",
            "python",
            str(_REPO_ROOT / "demos" / "research-assistant" / "run.py"),
        ],
        "replay_command": [
            "uv",
            "run",
            "--project",
            str(_REPO_ROOT / "sdk"),
            "--extra",
            "langgraph",
            "--extra",
            "demos",
            "python",
            str(_REPO_ROOT / "demos" / "research-assistant" / "replay_entrypoint.py"),
        ],
    },
    "content-pipeline": {
        "run_command": [
            "uv",
            "run",
            "--project",
            str(_REPO_ROOT / "sdk"),
            "--extra",
            "crewai",
            "python",
            str(_REPO_ROOT / "demos" / "content-pipeline" / "run.py"),
        ],
        "replay_command": [
            "uv",
            "run",
            "--project",
            str(_REPO_ROOT / "sdk"),
            "--extra",
            "crewai",
            "python",
            str(_REPO_ROOT / "demos" / "content-pipeline" / "replay_entrypoint.py"),
        ],
    },
}


def verify_one(demo: str) -> bool:
    config = _DEMOS[demo]
    print(f"=== {demo} ===")

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        run_result = subprocess.run(
            [*config["run_command"], "--endpoint", _UNREACHABLE_ENDPOINT],
            capture_output=True,
            text=True,
            cwd=workdir,
            check=False,
        )
        match = _RUN_ID_PATTERN.search(run_result.stdout)
        if not match:
            print(
                f"verify_fidelity: no TRAZO_RUN_ID in {demo}'s output", file=sys.stderr
            )
            print(run_result.stdout, file=sys.stderr)
            print(run_result.stderr, file=sys.stderr)
            return False
        run_id = match.group(1)

        write_bundle_cache(
            spool_dir=workdir / ".trazo" / "spool",
            cache_dir=workdir / ".trazo" / "cache",
            run_id=run_id,
        )

        replay_result = subprocess.run(
            [
                *config["replay_command"],
                run_id,
                "--endpoint",
                _UNREACHABLE_ENDPOINT,
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=workdir,
            check=False,
        )
        try:
            report = json.loads(replay_result.stdout)
        except json.JSONDecodeError:
            print(
                f"verify_fidelity: {demo} replay printed non-JSON output",
                file=sys.stderr,
            )
            print(replay_result.stdout, file=sys.stderr)
            print(replay_result.stderr, file=sys.stderr)
            return False

    print(json.dumps(report, indent=2))
    ok = (
        report["boundary_fidelity"] == 1.0
        and report["state_fidelity"] == 1.0
        and not report["divergences"]
    )
    if ok:
        print(f"verify_fidelity: {demo} replayed with 100% fidelity, zero divergences")
    else:
        print(
            f"verify_fidelity: {demo} did NOT replay with full fidelity",
            file=sys.stderr,
        )
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("demo", choices=[*sorted(_DEMOS), "all"])
    args = parser.parse_args()

    demos = sorted(_DEMOS) if args.demo == "all" else [args.demo]
    results = {demo: verify_one(demo) for demo in demos}

    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
