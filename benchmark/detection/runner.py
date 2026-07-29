#!/usr/bin/env python3
"""Offline detector scorer (TRZ-P5-05, AI_DEBUGGER.md §3): feeds the
labeled failure corpus (TRZ-P5-02, ``benchmark/corpus/failure_index.json``)
through the *same* detector code the live ``DetectorWorker`` runs online,
scoring against the chaos harness's ground truth
(``tags.injected_failure = {class, start_call_index}``).

    uv run --project sdk python benchmark/detection/runner.py \\
        [--index-path benchmark/corpus/failure_index.json] \\
        [--cache-dir benchmark/corpus/_runs/.trazo/cache] \\
        [--out benchmark/detection/results.md]

Runs under either project's venv (only needs ``trazo_server``'s own
deps, pydantic + stdlib, both of which ``sdk``'s env already carries) —
``uv run --project sdk`` matches how CI invokes every ``benchmark/``
test (``uv run --project sdk pytest benchmark/ -q``, ci.yml), so this
matches that rather than needing its own dedicated CI step.

One command regenerates RESEARCH.md's RQ2 table. No bus, no worker: each
run's cached replay bundle (built by ``generate_failure_corpus.py``, the
same ``spool_to_bundle.py`` trick ``benchmark/fidelity`` uses) is replayed
in-process through a fresh ``RunWindow`` + ``LoopDetector``/
``BudgetDetector``/``ThrashDetector`` — exactly the objects
``DetectorWorker._handle_event`` dispatches to online, so tuning a
threshold here and PR'ing the new default is the whole workflow
(AI_DEBUGGER.md §3: "same code online and offline is the point").

Drift has no rule detector (AI_DEBUGGER.md §5's stretch classifier,
TRZ-P5-07) so it is reported as corpus size only, plus a spurious-fire
note — it is never scored against a rule detector that was never meant
to catch it.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONTROL_PLANE_SRC = _REPO_ROOT / "control-plane" / "src"
sys.path.insert(0, str(_CONTROL_PLANE_SRC))

from pydantic import ValidationError  # noqa: E402

from trazo_server.detectors.base import Detector, RunWindow  # noqa: E402
from trazo_server.detectors.budget import BudgetDetector  # noqa: E402
from trazo_server.detectors.loop import LoopDetector  # noqa: E402
from trazo_server.detectors.thrash import ThrashDetector  # noqa: E402
from trazo_server.events import Event, EventAdapter  # noqa: E402

_DEFAULT_INDEX_PATH = _REPO_ROOT / "benchmark" / "corpus" / "failure_index.json"
_DEFAULT_CACHE_DIR = _REPO_ROOT / "benchmark" / "corpus" / "_runs" / ".trazo" / "cache"
_DEFAULT_OUT_PATH = _REPO_ROOT / "benchmark" / "detection" / "results.md"

# Ground truth class -> the boundary kind that class's chaos injector
# corrupts (demos/*/chaos_run.py's own docstrings), used to translate a
# 0-based ``start_call_index`` into the onset event's seq for latency.
_CLASS_BOUNDARY_KIND: dict[str, str] = {
    "loop": "tool.call",
    "budget": "llm.call",
    "thrash": "tool.call",
}
_RULE_DETECTOR_CLASSES = ("loop", "budget", "thrash")


@dataclass(frozen=True)
class CorpusEntry:
    run_id: str
    project: str
    framework: str
    label: str


@dataclass(frozen=True)
class RunResult:
    entry: CorpusEntry
    onset_seq: int | None
    first_fire_seq: dict[str, int]
    any_detector_fired: bool


def load_entries(index_path: Path) -> list[CorpusEntry]:
    raw = json.loads(index_path.read_text(encoding="utf-8"))
    return [
        CorpusEntry(
            run_id=item["run_id"],
            project=item["project"],
            framework=item["framework"],
            label=item["label"],
        )
        for item in raw
    ]


def load_bundle(cache_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    lines = [
        line
        for line in cache_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    manifest = json.loads(lines[0])
    events = [json.loads(line) for line in lines[1:]]
    return manifest, events


def bundle_event_to_event(
    manifest: dict[str, Any], raw: dict[str, Any]
) -> Event | None:
    """Reconstruct a typed ``Event`` from one replay-bundle event line —
    the bundle format drops ``schema``/``project`` (only the manifest
    carries those), so they're stitched back on here."""
    envelope = {**raw, "schema": "trazo.v1", "project": manifest["project_id"]}
    try:
        return EventAdapter.validate_python(envelope)
    except ValidationError:
        return None


def onset_seq(events: list[Event], kind: str, call_index: int) -> int | None:
    """The seq of the ``call_index``-th (0-based) event of ``kind``, in
    seq order — the point the chaos injector's ground truth says the
    fault started being observable in the stream."""
    matching = sorted((e for e in events if e.kind == kind), key=lambda e: e.seq)
    if call_index >= len(matching):
        return None
    return matching[call_index].seq


def score_run(
    entry: CorpusEntry, events: list[Event], detectors: list[Detector]
) -> RunResult:
    window = RunWindow(entry.run_id)
    first_fire: dict[str, int] = {}
    for event in sorted(events, key=lambda e: e.seq):
        window.record(event)
        for detector in detectors:
            detection = detector.on_event(event, window)
            if detection is not None and detector.id not in first_fire:
                first_fire[detector.id] = event.seq

    start_call_index = None
    if entry.label in _RULE_DETECTOR_CLASSES:
        tags = manifest_tags(events)
        start_call_index = tags.get("start_call_index") if tags else None

    onset = None
    if entry.label in _CLASS_BOUNDARY_KIND and start_call_index is not None:
        onset = onset_seq(events, _CLASS_BOUNDARY_KIND[entry.label], start_call_index)

    return RunResult(
        entry=entry,
        onset_seq=onset,
        first_fire_seq=first_fire,
        any_detector_fired=bool(first_fire),
    )


def manifest_tags(events: list[Event]) -> dict[str, Any] | None:
    started = next((e for e in events if e.kind == "run.started"), None)
    if started is None:
        return None
    tags = started.payload.tags  # type: ignore[union-attr]
    injected: dict[str, Any] | None = tags.get("injected_failure")
    return injected


@dataclass(frozen=True)
class ClassMetrics:
    label: str
    corpus_size: int
    true_positives: int
    false_negatives: int
    false_positives: int
    precision: float | None
    recall: float | None
    fpr_on_clean: float | None
    median_latency_events: float | None


def compute_class_metrics(label: str, results: list[RunResult]) -> ClassMetrics:
    labeled = [r for r in results if r.entry.label == label]
    not_labeled = [r for r in results if r.entry.label != label]
    clean = [r for r in results if r.entry.label == "clean"]

    tp = sum(1 for r in labeled if label in r.first_fire_seq)
    fn = len(labeled) - tp
    fp = sum(1 for r in not_labeled if label in r.first_fire_seq)

    recall = tp / len(labeled) if labeled else None
    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    fpr_on_clean = (
        sum(1 for r in clean if label in r.first_fire_seq) / len(clean)
        if clean
        else None
    )

    latencies = [
        r.first_fire_seq[label] - r.onset_seq
        for r in labeled
        if label in r.first_fire_seq and r.onset_seq is not None
    ]
    median_latency = float(statistics.median(latencies)) if latencies else None

    return ClassMetrics(
        label=label,
        corpus_size=len(labeled),
        true_positives=tp,
        false_negatives=fn,
        false_positives=fp,
        precision=precision,
        recall=recall,
        fpr_on_clean=fpr_on_clean,
        median_latency_events=median_latency,
    )


def _fmt(value: float | None, *, pct: bool = False) -> str:
    if value is None:
        return "n/a"
    return f"{value:.0%}" if pct else f"{value:.1f}"


def render_report(
    class_metrics: list[ClassMetrics], *, drift_corpus_size: int, clean_corpus_size: int
) -> str:
    lines = [
        "# RQ2 — Detector precision/recall (TRZ-P5-05)",
        "",
        "Regenerate with `uv run --project sdk python benchmark/detection/runner.py`.",
        "",
        "| Class | Corpus | TP | FN | FP | Precision | Recall | FPR (clean) "
        "| Median latency (events) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for m in class_metrics:
        lines.append(
            f"| {m.label} | {m.corpus_size} | {m.true_positives} | "
            f"{m.false_negatives} | {m.false_positives} | "
            f"{_fmt(m.precision, pct=True)} | {_fmt(m.recall, pct=True)} | "
            f"{_fmt(m.fpr_on_clean, pct=True)} | "
            f"{_fmt(m.median_latency_events)} |"
        )
    lines.append("")
    lines.append(
        f"Clean corpus: {clean_corpus_size} runs. Drift corpus: "
        f"{drift_corpus_size} runs — no rule detector targets drift "
        "(AI_DEBUGGER.md §5's stretch classifier, TRZ-P5-07); reported "
        "as corpus size only."
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-path", type=Path, default=_DEFAULT_INDEX_PATH)
    parser.add_argument("--cache-dir", type=Path, default=_DEFAULT_CACHE_DIR)
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT_PATH)
    args = parser.parse_args(argv)

    entries = load_entries(args.index_path)
    detectors: list[Detector] = [LoopDetector(), BudgetDetector(), ThrashDetector()]

    results: list[RunResult] = []
    skipped = 0
    for entry in entries:
        cache_path = args.cache_dir / f"{entry.run_id}.ndjson"
        if not cache_path.exists():
            skipped += 1
            continue
        manifest, raw_events = load_bundle(cache_path)
        events = [
            e
            for raw in raw_events
            if (e := bundle_event_to_event(manifest, raw)) is not None
        ]
        results.append(score_run(entry, events, detectors))

    class_metrics = [compute_class_metrics(c, results) for c in _RULE_DETECTOR_CLASSES]
    drift_size = sum(1 for r in results if r.entry.label == "drift")
    clean_size = sum(1 for r in results if r.entry.label == "clean")

    report = render_report(
        class_metrics, drift_corpus_size=drift_size, clean_corpus_size=clean_size
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(report)
    if skipped:
        print(
            f"runner: skipped {skipped} corpus entries with no cached bundle "
            f"on disk (re-run generate_failure_corpus.py to regenerate)",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
