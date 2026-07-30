#!/usr/bin/env python3
"""Fidelity harness (TRZ-P4-07): one command regenerates RESEARCH.md's
RQ1 table from ``benchmark/corpus/index.json``.

    python benchmark/fidelity/run_harness.py [--corpus-index PATH] \\
        [--endpoint http://localhost:8420] [--out PATH]

For each corpus entry, runs the matching demo's ``replay_entrypoint.py
<run_id> --json`` as its own subprocess (never both demos' same-named
``llm``/``agent`` modules in one interpreter — see each entrypoint
script's own docstring) via ``uv run``, parses its ``trazo verify``-shaped
JSON report, and aggregates boundary fidelity / state fidelity / replay
overhead — RESEARCH.md RQ1's three headline metrics — across the whole
corpus and per project/framework.

Writes a markdown table to ``--out`` (default ``benchmark/fidelity/
results.md``); RESEARCH.md links to that file rather than embedding it,
so this script is the only thing that ever needs to regenerate it.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "benchmark"))

from adapter import ReplayAdapter, SubprocessReplayAdapter  # noqa: E402

_DEFAULT_CORPUS_INDEX = _REPO_ROOT / "benchmark" / "corpus" / "index.json"
_DEFAULT_RESULTS_PATH = _REPO_ROOT / "benchmark" / "fidelity" / "results.md"

# project name (benchmark/corpus/archive_run.py's own field) -> the
# ReplayAdapter (benchmark/adapter.py) that knows how to replay it. A
# third party benchmarking their own tool registers a new project name
# here (or their own ReplayAdapter implementation) rather than needing
# to touch _replay_one/main below.
_DEMO_ADAPTERS: dict[str, ReplayAdapter] = {
    "research-assistant": SubprocessReplayAdapter(
        [
            "uv",
            "run",
            "--project",
            "sdk",
            "--extra",
            "langgraph",
            "--extra",
            "demos",
            "python",
            str(_REPO_ROOT / "demos" / "research-assistant" / "replay_entrypoint.py"),
        ]
    ),
    "content-pipeline": SubprocessReplayAdapter(
        [
            "uv",
            "run",
            "--project",
            "sdk",
            "--extra",
            "crewai",
            "python",
            str(_REPO_ROOT / "demos" / "content-pipeline" / "replay_entrypoint.py"),
        ]
    ),
}


class UnknownProjectError(Exception):
    """Raised for a corpus entry whose project has no registered demo
    command — a new demo landed without teaching this harness about it."""


@dataclass(frozen=True)
class FidelityResult:
    run_id: str
    project: str
    framework: str
    boundary_fidelity: float
    state_fidelity: float
    replay_overhead: float | None
    divergence_count: int


def _replay_one(entry: dict[str, Any], *, endpoint: str) -> FidelityResult:
    project = entry["project"]
    if project not in _DEMO_ADAPTERS:
        raise UnknownProjectError(
            f"no replay adapter registered for project {project!r} "
            f"(known: {sorted(_DEMO_ADAPTERS)})"
        )
    report = _DEMO_ADAPTERS[project].replay(entry["run_id"], endpoint=endpoint)
    return FidelityResult(
        run_id=entry["run_id"],
        project=project,
        framework=entry["framework"],
        boundary_fidelity=report["boundary_fidelity"],
        state_fidelity=report["state_fidelity"],
        replay_overhead=report.get("replay_overhead"),
        divergence_count=len(report["divergences"]),
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _render_table(results: list[FidelityResult]) -> str:
    header = (
        "| Project | Runs | Boundary fidelity | State fidelity "
        "| Replay overhead | Divergences |"
    )
    lines = [
        "<!-- Regenerate with: python benchmark/fidelity/run_harness.py -->",
        "",
        header,
        "|---|---|---|---|---|---|",
    ]

    by_project: dict[str, list[FidelityResult]] = {}
    for result in results:
        by_project.setdefault(result.project, []).append(result)

    for project in sorted(by_project):
        rows = by_project[project]
        overheads = [r.replay_overhead for r in rows if r.replay_overhead is not None]
        lines.append(
            f"| {project} | {len(rows)} "
            f"| {_mean([r.boundary_fidelity for r in rows]):.2%} "
            f"| {_mean([r.state_fidelity for r in rows]):.2%} "
            f"| {_mean(overheads):.2f}x "
            f"| {sum(r.divergence_count for r in rows)} |"
        )

    if results:
        overheads = [
            r.replay_overhead for r in results if r.replay_overhead is not None
        ]
        lines.append(
            f"| **all** | {len(results)} "
            f"| {_mean([r.boundary_fidelity for r in results]):.2%} "
            f"| {_mean([r.state_fidelity for r in results]):.2%} "
            f"| {_mean(overheads):.2f}x "
            f"| {sum(r.divergence_count for r in results)} |"
        )
    else:
        lines.append("| *(no corpus entries yet)* | 0 | - | - | - | - |")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-index", type=Path, default=_DEFAULT_CORPUS_INDEX)
    parser.add_argument("--endpoint", default="http://localhost:8420")
    parser.add_argument("--out", type=Path, default=_DEFAULT_RESULTS_PATH)
    args = parser.parse_args(argv)

    entries: list[dict[str, Any]] = []
    if args.corpus_index.exists():
        entries = json.loads(args.corpus_index.read_text(encoding="utf-8"))

    results = [_replay_one(entry, endpoint=args.endpoint) for entry in entries]

    table = _render_table(results)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(table, encoding="utf-8")
    print(table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
