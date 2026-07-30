"""Unit tests for the offline detector scorer (TRZ-P5-05)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Not relying on runner.py's own sys.path.insert side effect (which would
# make this import order-fragile against ruff's import sorter -- "adapter"
# and "runner" fall in the same unclassified-local-module bucket ruff
# wants alphabetized together, but adapter must not resolve before
# runner.py's sys.path.insert has actually run): this file sets up its
# own path to benchmark/ so either import order works.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "benchmark"))

from adapter import TrazoDetectorAdapter
from runner import (
    ClassMetrics,
    CorpusEntry,
    RunResult,
    bundle_event_to_event,
    compute_class_metrics,
    load_bundle,
    load_entries,
    main,
    manifest_tags,
    onset_seq,
    render_report,
    score_run,
)

from trazo_server.detectors.loop import LoopDetector
from trazo_server.events import Event

_RUN_ID = "run_1"


def _event(seq: int, kind: str, **overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "run_id": _RUN_ID,
        "seq": seq,
        "event_id": f"evt_{seq}",
        "kind": kind,
        "ts": "2026-01-01T00:00:00Z",
        "step_id": None,
        "agent_id": None,
        "fingerprint": None,
        "payload": {},
        "blobs": [],
    }
    defaults.update(overrides)
    return defaults


def _typed(manifest: dict[str, Any], raw: dict[str, Any]) -> Event:
    event = bundle_event_to_event(manifest, raw)
    assert event is not None
    return event


def _manifest(*, project_id: str = "research-assistant") -> dict[str, Any]:
    return {"schema": "trazo.replay-bundle.v1", "project_id": project_id}


def test_load_entries__reads_manifest_json(tmp_path: Path) -> None:
    index_path = tmp_path / "failure_index.json"
    index_path.write_text(
        json.dumps(
            [
                {
                    "run_id": "run_1",
                    "project": "research-assistant",
                    "framework": "langgraph",
                    "label": "loop",
                    "recorded_at": "2026-01-01T00:00:00Z",
                }
            ]
        ),
        encoding="utf-8",
    )

    entries = load_entries(index_path)

    assert entries == [
        CorpusEntry(
            run_id="run_1",
            project="research-assistant",
            framework="langgraph",
            label="loop",
        )
    ]


def test_load_bundle__splits_manifest_from_event_lines(tmp_path: Path) -> None:
    cache_path = tmp_path / "run_1.ndjson"
    cache_path.write_text(
        json.dumps({"schema": "trazo.replay-bundle.v1"})
        + "\n"
        + json.dumps(_event(0, "run.started"))
        + "\n",
        encoding="utf-8",
    )

    manifest, events = load_bundle(cache_path)

    assert manifest == {"schema": "trazo.replay-bundle.v1"}
    assert len(events) == 1
    assert events[0]["kind"] == "run.started"


def test_bundle_event_to_event__stitches_schema_and_project_back_on() -> None:
    manifest = _manifest(project_id="content-pipeline")
    raw = _event(
        0,
        "run.started",
        payload={
            "framework": "crewai",
            "framework_version": "1.0",
            "sdk_version": "0.1.0",
            "entry_input": {},
            "tags": {},
        },
    )

    event = bundle_event_to_event(manifest, raw)

    assert event is not None
    assert event.project == "content-pipeline"
    assert event.run_id == _RUN_ID


def test_bundle_event_to_event__returns_none_on_invalid_shape() -> None:
    manifest = _manifest()
    raw = _event(0, "not.a.real.kind")

    assert bundle_event_to_event(manifest, raw) is None


def test_manifest_tags__extracts_injected_failure_from_run_started() -> None:
    manifest = _manifest()
    events = [
        _typed(
            manifest,
            _event(
                0,
                "run.started",
                payload={
                    "framework": "langgraph",
                    "framework_version": "1.0",
                    "sdk_version": "0.1.0",
                    "entry_input": {},
                    "tags": {
                        "injected_failure": {"class": "loop", "start_call_index": 0}
                    },
                },
            ),
        )
    ]

    assert manifest_tags(events) == {"class": "loop", "start_call_index": 0}


def test_manifest_tags__none_when_tags_absent() -> None:
    manifest = _manifest()
    events = [
        _typed(
            manifest,
            _event(
                0,
                "run.started",
                payload={
                    "framework": "langgraph",
                    "framework_version": "1.0",
                    "sdk_version": "0.1.0",
                    "entry_input": {},
                    "tags": {},
                },
            ),
        )
    ]

    assert manifest_tags(events) is None


def _tool_call(manifest: dict[str, Any], *, seq: int, fingerprint: str) -> Event:
    return _typed(
        manifest,
        _event(
            seq,
            "tool.call",
            fingerprint=fingerprint,
            payload={
                "tool_name": "web_search",
                "args": {},
                "result": "no results",
                "status": "ok",
                "latency_ms": 1.0,
                "side_effect_class": "external",
            },
        ),
    )


def test_onset_seq__finds_the_nth_event_of_a_kind() -> None:
    manifest = _manifest()
    events = [
        _tool_call(manifest, seq=0, fingerprint="sha256:" + "a" * 64),
        _tool_call(manifest, seq=5, fingerprint="sha256:" + "b" * 64),
        _tool_call(manifest, seq=10, fingerprint="sha256:" + "c" * 64),
    ]

    assert onset_seq(events, "tool.call", 0) == 0
    assert onset_seq(events, "tool.call", 2) == 10
    assert onset_seq(events, "tool.call", 3) is None


def test_score_run__loop_detector_fires_and_first_fire_seq_is_recorded() -> None:
    manifest = _manifest()
    fp = "sha256:" + "a" * 64
    events = [_tool_call(manifest, seq=i * 5, fingerprint=fp) for i in range(4)]
    entry = CorpusEntry(
        run_id=_RUN_ID,
        project="research-assistant",
        framework="langgraph",
        label="loop",
    )

    result = score_run(
        entry,
        events,
        TrazoDetectorAdapter(detectors=[LoopDetector(min_repeats=4, window_events=20)]),
    )

    assert result.first_fire_seq == {"loop": 15}
    assert result.any_detector_fired is True


def test_score_run__no_detections_when_nothing_repeats() -> None:
    manifest = _manifest()
    events = [
        _tool_call(manifest, seq=i, fingerprint=f"sha256:{chr(97 + i) * 64}")
        for i in range(4)
    ]
    entry = CorpusEntry(
        run_id=_RUN_ID,
        project="research-assistant",
        framework="langgraph",
        label="clean",
    )

    result = score_run(
        entry,
        events,
        TrazoDetectorAdapter(detectors=[LoopDetector(min_repeats=4, window_events=20)]),
    )

    assert result.first_fire_seq == {}
    assert result.any_detector_fired is False


def test_compute_class_metrics__precision_recall_fpr_and_latency() -> None:
    def _entry(label: str) -> CorpusEntry:
        return CorpusEntry(run_id="r", project="p", framework="f", label=label)

    results = [
        RunResult(
            entry=_entry("loop"),
            onset_seq=10,
            first_fire_seq={"loop": 25},
            any_detector_fired=True,
        ),
        RunResult(
            entry=_entry("loop"),
            onset_seq=10,
            first_fire_seq={},
            any_detector_fired=False,
        ),
        RunResult(
            entry=_entry("clean"),
            onset_seq=None,
            first_fire_seq={"loop": 5},
            any_detector_fired=True,
        ),
        RunResult(
            entry=_entry("clean"),
            onset_seq=None,
            first_fire_seq={},
            any_detector_fired=False,
        ),
    ]

    metrics = compute_class_metrics("loop", results)

    assert metrics.corpus_size == 2
    assert metrics.true_positives == 1
    assert metrics.false_negatives == 1
    assert metrics.false_positives == 1
    assert metrics.precision == 0.5
    assert metrics.recall == 0.5
    assert metrics.fpr_on_clean == 0.5
    assert metrics.median_latency_events == 15.0


def test_compute_class_metrics__empty_class_reports_none_not_zero_division() -> None:
    metrics = compute_class_metrics("thrash", [])

    assert metrics.corpus_size == 0
    assert metrics.precision is None
    assert metrics.recall is None
    assert metrics.fpr_on_clean is None
    assert metrics.median_latency_events is None


def test_render_report__includes_every_class_row_and_corpus_footnote() -> None:
    metrics = [
        ClassMetrics(
            label="loop",
            corpus_size=2,
            true_positives=1,
            false_negatives=1,
            false_positives=0,
            precision=1.0,
            recall=0.5,
            fpr_on_clean=0.0,
            median_latency_events=3.0,
        )
    ]

    report = render_report(metrics, drift_corpus_size=5, clean_corpus_size=7)

    assert "loop" in report
    assert "50%" in report
    assert "Clean corpus: 7 runs" in report
    assert "Drift corpus: 5 runs" in report


def test_main__end_to_end_against_a_small_fixture_corpus(tmp_path: Path) -> None:
    manifest = _manifest()
    fp = "sha256:" + "a" * 64

    def _write_bundle(run_id: str, events: list[dict[str, Any]]) -> None:
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(exist_ok=True)
        lines = [json.dumps(manifest)] + [json.dumps(e) for e in events]
        (cache_dir / f"{run_id}.ndjson").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

    started = _event(
        0,
        "run.started",
        payload={
            "framework": "langgraph",
            "framework_version": "1.0",
            "sdk_version": "0.1.0",
            "entry_input": {},
            "tags": {"injected_failure": {"class": "loop", "start_call_index": 0}},
        },
    )
    loop_events = [started] + [
        _event(
            (i + 1) * 5,
            "tool.call",
            fingerprint=fp,
            payload={
                "tool_name": "web_search",
                "args": {},
                "result": "x",
                "status": "ok",
                "latency_ms": 1.0,
                "side_effect_class": "external",
            },
        )
        for i in range(4)
    ]
    _write_bundle("run_loop", loop_events)

    clean_started = _event(
        0,
        "run.started",
        payload={
            "framework": "langgraph",
            "framework_version": "1.0",
            "sdk_version": "0.1.0",
            "entry_input": {},
            "tags": {},
        },
    )
    _write_bundle("run_clean", [clean_started])

    index_path = tmp_path / "failure_index.json"
    index_path.write_text(
        json.dumps(
            [
                {
                    "run_id": "run_loop",
                    "project": "research-assistant",
                    "framework": "langgraph",
                    "label": "loop",
                    "recorded_at": "2026-01-01T00:00:00Z",
                },
                {
                    "run_id": "run_clean",
                    "project": "research-assistant",
                    "framework": "langgraph",
                    "label": "clean",
                    "recorded_at": "2026-01-01T00:00:00Z",
                },
            ]
        ),
        encoding="utf-8",
    )
    out_path = tmp_path / "results.md"

    exit_code = main(
        [
            "--index-path",
            str(index_path),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--out",
            str(out_path),
        ]
    )

    assert exit_code == 0
    report = out_path.read_text(encoding="utf-8")
    assert "| loop | 1 | 1 | 0 | 0 |" in report
