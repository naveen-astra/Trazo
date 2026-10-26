#!/usr/bin/env python3
"""Score the goal-drift judge against the labeled failure corpus.

    uv run --project sdk python benchmark/detection/drift_runner.py \\
        --model qwen2.5:3b [--base-url http://localhost:11434/v1] \\
        [--skip-first 8] [--max-per-group 25] [--out results-drift-<model>.md]

Separate from ``runner.py`` on purpose. That one scores the deterministic
rule detectors, reproduces byte for byte from the committed corpus, and
needs nothing running. This one asks a language model, so its numbers
belong to a named model and may move between runs (AI_DEBUGGER.md §5: "the
benchmark must not depend on a 7B model's mood"). It drives
``trazo_server.drift.DriftDetector`` through the same ``RunWindow``
dispatch the worker uses.

``--skip-first N`` leaves out the first N runs of each (project, label)
group: those are the development set the judge's prompt was tuned on, and
the reported numbers should come from runs it was not tuned on.

Progress is saved to ``--cache`` after every run, so an interrupted scoring
resumes where it stopped; delete the file (or change the model) to rescore.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import runner
from adapter import TrazoDetectorAdapter

from trazo_server.drift import DriftDetector, DriftJudge

_DETECTION_DIR = runner._REPO_ROOT / "benchmark" / "detection"


def _slug(model: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", model.lower()).strip("-")


def _group_key(entry: runner.CorpusEntry) -> tuple[str, str]:
    return (entry.project, entry.label)


def select_entries(
    entries: list[runner.CorpusEntry], *, skip_first: int, max_per_group: int | None
) -> list[runner.CorpusEntry]:
    """The entries to score: per (project, label) group, in corpus order,
    minus the development set, capped."""
    seen: dict[tuple[str, str], int] = defaultdict(int)
    chosen = []
    for entry in entries:
        position = seen[_group_key(entry)]
        seen[_group_key(entry)] += 1
        if position < skip_first:
            continue
        if max_per_group is not None and position - skip_first >= max_per_group:
            continue
        chosen.append(entry)
    return chosen


def _fire_seq(detections: list[Any], seq_by_event_id: dict[str, int]) -> int | None:
    for detection in detections:
        if detection.detector != "drift":
            continue
        seqs = [
            seq_by_event_id[e]
            for e in detection.evidence_event_ids
            if e in seq_by_event_id
        ]
        return max(seqs) if seqs else None
    return None


def score(
    entries: list[runner.CorpusEntry],
    cache_dir: Path,
    detector: DriftDetector,
    *,
    cache: dict[str, Any],
    cache_path: Path,
) -> list[runner.RunResult]:
    adapter = TrazoDetectorAdapter(detectors=[], drift=detector)
    results: list[runner.RunResult] = []
    for number, entry in enumerate(entries, start=1):
        path = cache_dir / f"{entry.run_id}.ndjson"
        if not path.exists():
            continue
        manifest, raw = runner.load_bundle(path)
        events = [
            e
            for r in raw
            if (e := runner.bundle_event_to_event(manifest, r)) is not None
        ]
        seq_by_event_id = {e.event_id: e.seq for e in events}

        if entry.run_id in cache:
            fire_seq = cache[entry.run_id]["fire_seq"]
            seconds = None
        else:
            started = time.monotonic()
            fire_seq = _fire_seq(adapter.detect(events), seq_by_event_id)
            seconds = round(time.monotonic() - started, 1)
            cache[entry.run_id] = {"fire_seq": fire_seq, "seconds": seconds}
            cache_path.write_text(json.dumps(cache), encoding="utf-8")
            print(
                f"[{number}/{len(entries)}] {entry.project:18} {entry.label:7} "
                f"fired={fire_seq is not None!s:5} {seconds}s",
                file=sys.stderr,
                flush=True,
            )

        onset = None
        if entry.label == "drift":
            tags = runner.manifest_tags(events)
            index = tags.get("start_call_index") if tags else None
            if index is not None:
                onset = runner.onset_seq(events, "llm.call", index)
        results.append(
            runner.RunResult(
                entry=entry,
                onset_seq=onset,
                first_fire_seq={} if fire_seq is None else {"drift": fire_seq},
                any_detector_fired=fire_seq is not None,
            )
        )
    return results


def _row(name: str, m: runner.ClassMetrics) -> str:
    return (
        f"| {name} | {m.corpus_size} | {m.true_positives} | {m.false_negatives} | "
        f"{m.false_positives} | {runner._fmt(m.precision, pct=True)} | "
        f"{runner._fmt(m.recall, pct=True)} | {runner._fmt(m.fpr_on_clean, pct=True)} |"
    )


def render(
    results: list[runner.RunResult],
    cache: dict[str, Any],
    *,
    model: str,
    base_url: str,
    every_n: int,
    confirmations: int,
    skip_first: int,
) -> str:
    lines = [
        "# Goal-drift judge (opt-in), scored on the failure corpus",
        "",
        f"Judge model: `{model}` at `{base_url}`; judging every {every_n} model "
        f"calls, raising after {confirmations} consecutive off-task verdicts, "
        f"at most once per run. Scored {datetime.now(timezone.utc):%Y-%m-%d}. "
        "Regenerate with `uv run --project sdk python "
        "benchmark/detection/drift_runner.py --model <model> --skip-first 8`.",
        "",
        f"The first {skip_first} runs of each (project, label) group are the "
        "development set the prompt was tuned on and are excluded here.",
        "",
        "A model's verdicts are not deterministic across models, versions or "
        "hardware: treat these as one measurement of one model, not a property "
        "of the detector. The rule detectors' numbers (`results.md`) are "
        "reproducible; these are not guaranteed to be.",
        "",
        "| Slice | Drift runs | Caught | Missed | False alarms | Precision "
        "| Recall | FPR (clean) |",
        "|---|---|---|---|---|---|---|---|",
        _row("all", runner.compute_class_metrics("drift", results)),
    ]
    for project in sorted({r.entry.project for r in results}):
        subset = [r for r in results if r.entry.project == project]
        lines.append(_row(project, runner.compute_class_metrics("drift", subset)))

    overall = runner.compute_class_metrics("drift", results)
    if overall.fpr_on_clean is not None and overall.fpr_on_clean >= 0.5:
        lines += [
            "",
            f"**Verdict: do not use this judge.** It raised drift on "
            f"{overall.fpr_on_clean:.0%} of clean runs, so its catches of real "
            "drift say nothing: it does not separate drifted runs from healthy "
            "ones. Try a stronger model.",
        ]

    fired_by_label: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in results:
        fired_by_label[r.entry.label][0] += 1
        fired_by_label[r.entry.label][1] += "drift" in r.first_fire_seq
    lines += ["", "Drift judge firing, by corpus label:", ""]
    lines += ["| Label | Runs | Judge raised drift |", "|---|---|---|"]
    for label, (total, fired) in sorted(fired_by_label.items()):
        lines.append(f"| {label} | {total} | {fired} |")

    latencies = [
        r.first_fire_seq["drift"] - r.onset_seq
        for r in results
        if r.entry.label == "drift"
        and "drift" in r.first_fire_seq
        and r.onset_seq is not None
    ]
    if latencies:
        lines += [
            "",
            f"Median detection latency after the drift began: "
            f"{statistics.median(latencies):.0f} events.",
        ]
    seconds = [c["seconds"] for c in cache.values() if c.get("seconds")]
    if seconds:
        lines += [
            "",
            f"Judging cost: median {statistics.median(seconds):.1f}s per run "
            f"on the scoring machine.",
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="http://localhost:11434/v1")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--every-n", type=int, default=2)
    parser.add_argument("--confirmations", type=int, default=2)
    parser.add_argument("--skip-first", type=int, default=0)
    parser.add_argument("--max-per-group", type=int, default=None)
    parser.add_argument("--index-path", type=Path, default=runner._DEFAULT_INDEX_PATH)
    parser.add_argument("--cache-dir", type=Path, default=runner._DEFAULT_CACHE_DIR)
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)

    # One report and one resumable cache per judge model, so scoring a second
    # model never overwrites the first's numbers.
    slug = _slug(args.model)
    args.cache = args.cache or _DETECTION_DIR / f".drift-cache-{slug}.json"
    args.out = args.out or _DETECTION_DIR / f"results-drift-{slug}.md"

    entries = select_entries(
        runner.load_entries(args.index_path),
        skip_first=args.skip_first,
        max_per_group=args.max_per_group,
    )
    cache: dict[str, Any] = {}
    if args.cache.exists():
        cache = json.loads(args.cache.read_text(encoding="utf-8"))
    judge = DriftJudge(
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key,
        timeout_seconds=120,
    )
    detector = DriftDetector(
        judge, every_n_llm_calls=args.every_n, confirmations=args.confirmations
    )
    results = score(
        entries, args.cache_dir, detector, cache=cache, cache_path=args.cache
    )
    report = render(
        results,
        cache,
        model=args.model,
        base_url=args.base_url,
        every_n=args.every_n,
        confirmations=args.confirmations,
        skip_first=args.skip_first,
    )
    print(report)
    if not args.no_write:
        args.out.write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
