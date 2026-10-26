"""Unit tests for the opt-in drift judge scorer. No model is contacted."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "benchmark"))

import drift_runner
from runner import CorpusEntry, RunResult


def _entry(number: int, project: str, label: str) -> CorpusEntry:
    return CorpusEntry(
        run_id=f"run_{project}_{label}_{number}",
        project=project,
        framework="langgraph",
        label=label,
    )


def _corpus() -> list[CorpusEntry]:
    return [
        _entry(n, project, label)
        for project in ("a", "b")
        for label in ("clean", "drift")
        for n in range(10)
    ]


def test_select_entries__skips_the_development_set_in_every_group() -> None:
    chosen = drift_runner.select_entries(_corpus(), skip_first=8, max_per_group=None)

    assert len(chosen) == 4 * 2  # two left in each of four groups
    assert {e.run_id.rsplit("_", 1)[1] for e in chosen} == {"8", "9"}


def test_select_entries__caps_each_group_after_the_skip() -> None:
    chosen = drift_runner.select_entries(_corpus(), skip_first=2, max_per_group=3)

    assert len(chosen) == 4 * 3
    assert {e.run_id.rsplit("_", 1)[1] for e in chosen} == {"2", "3", "4"}


def test_select_entries__without_limits_keeps_everything_in_order() -> None:
    corpus = _corpus()

    assert (
        drift_runner.select_entries(corpus, skip_first=0, max_per_group=None) == corpus
    )


def test_slug__makes_a_model_name_safe_for_a_filename() -> None:
    assert drift_runner._slug("qwen2.5:3b") == "qwen2.5-3b"
    assert drift_runner._slug("Org/Some Model:Q4") == "org-some-model-q4"


def _results(*, clean_fired: int, clean_total: int) -> list[RunResult]:
    results = [
        RunResult(
            entry=_entry(n, "a", "clean"),
            onset_seq=None,
            first_fire_seq={"drift": 5} if n < clean_fired else {},
            any_detector_fired=n < clean_fired,
        )
        for n in range(clean_total)
    ]
    results.append(
        RunResult(
            entry=_entry(0, "a", "drift"),
            onset_seq=2,
            first_fire_seq={"drift": 6},
            any_detector_fired=True,
        )
    )
    return results


def _render(results: list[RunResult]) -> str:
    return drift_runner.render(
        results,
        {},
        model="m",
        base_url="http://x/v1",
        every_n=2,
        confirmations=2,
        skip_first=8,
    )


def test_render__warns_off_a_judge_that_flags_most_clean_runs() -> None:
    report = _render(_results(clean_fired=8, clean_total=10))

    assert "do not use this judge" in report
    assert "80%" in report


def test_render__has_no_warning_for_a_judge_that_stays_quiet_on_clean_runs() -> None:
    report = _render(_results(clean_fired=1, clean_total=10))

    assert "do not use this judge" not in report
    assert "| all | 1 | 1 | 0 | 1 |" in report  # the one drift run was caught
