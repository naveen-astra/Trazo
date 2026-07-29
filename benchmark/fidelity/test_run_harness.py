"""Unit tests for the fidelity harness (TRZ-P4-07)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from run_harness import (
    FidelityResult,
    UnknownProjectError,
    _mean,
    _render_table,
    _replay_one,
    main,
)


def test_mean__empty_list_is_zero() -> None:
    assert _mean([]) == 0.0


def test_mean__averages_values() -> None:
    assert _mean([1.0, 2.0, 3.0]) == 2.0


def _result(**overrides: Any) -> FidelityResult:
    defaults: dict[str, Any] = {
        "run_id": "run_1",
        "project": "research-assistant",
        "framework": "langgraph",
        "boundary_fidelity": 1.0,
        "state_fidelity": 1.0,
        "replay_overhead": 0.1,
        "divergence_count": 0,
    }
    defaults.update(overrides)
    return FidelityResult(**defaults)


def test_render_table__empty_results_says_no_entries() -> None:
    table = _render_table([])

    assert "no corpus entries yet" in table


def test_render_table__aggregates_per_project_and_overall() -> None:
    results = [
        _result(run_id="run_1", project="research-assistant", boundary_fidelity=1.0),
        _result(run_id="run_2", project="research-assistant", boundary_fidelity=0.5),
        _result(run_id="run_3", project="content-pipeline", boundary_fidelity=1.0),
    ]

    table = _render_table(results)

    assert "| research-assistant | 2 " in table
    assert "| content-pipeline | 1 " in table
    assert "| **all** | 3 " in table


def test_render_table__counts_divergences() -> None:
    results = [_result(divergence_count=2), _result(divergence_count=1)]

    table = _render_table(results)

    assert "| 3 |" in table  # total divergences in the "all" row


def test_replay_one__unknown_project_raises() -> None:
    with pytest.raises(UnknownProjectError, match="never-heard-of-this-demo"):
        _replay_one(
            {
                "run_id": "run_1",
                "project": "never-heard-of-this-demo",
                "framework": "x",
            },
            endpoint="http://example.test",
        )


def test_replay_one__parses_the_subprocess_json_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_report = {
        "boundary_fidelity": 0.9,
        "state_fidelity": 0.8,
        "replay_overhead": 0.15,
        "divergences": [{"kind": "llm.call"}],
    }

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert command[-1] == "--json"
        assert "run_1" in command
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(fake_report))

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = _replay_one(
        {"run_id": "run_1", "project": "research-assistant", "framework": "langgraph"},
        endpoint="http://example.test",
    )

    assert result.boundary_fidelity == 0.9
    assert result.state_fidelity == 0.8
    assert result.replay_overhead == 0.15
    assert result.divergence_count == 1


def test_main__writes_the_table_to_out_and_handles_a_missing_corpus_index(
    tmp_path: Path,
) -> None:
    out_path = tmp_path / "results.md"

    exit_code = main(
        [
            "--corpus-index",
            str(tmp_path / "does_not_exist.json"),
            "--out",
            str(out_path),
        ]
    )

    assert exit_code == 0
    assert "no corpus entries yet" in out_path.read_text(encoding="utf-8")
