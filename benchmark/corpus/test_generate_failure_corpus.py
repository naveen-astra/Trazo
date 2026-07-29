"""Unit tests for the failure-corpus generator (TRZ-P5-02)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from generate_failure_corpus import _load_entries, _run_once


def test_load_entries__empty_when_index_missing(tmp_path: Path) -> None:
    assert _load_entries(tmp_path / "does_not_exist.json") == []


def test_load_entries__reads_existing_index(tmp_path: Path) -> None:
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps([{"run_id": "run_1"}]), encoding="utf-8")

    assert _load_entries(index_path) == [{"run_id": "run_1"}]


def test_run_once__extracts_run_id_and_builds_the_bundle_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workdir = tmp_path
    spool_dir = workdir / ".trazo" / "spool"
    spool_dir.mkdir(parents=True)
    (spool_dir / "batch.ndjson").write_text(
        json.dumps(
            {
                "run_id": "run_abc",
                "project": "proj",
                "seq": 0,
                "event_id": "evt_1",
                "kind": "run.started",
                "ts": "2026-01-01T00:00:00Z",
                "payload": {"framework": "langgraph"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command, 0, stdout="the answer\nTRAZO_RUN_ID=run_abc\n"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("generate_failure_corpus._WORKDIR", workdir)

    run_id = _run_once(["some", "command"])

    assert run_id == "run_abc"
    assert (workdir / ".trazo" / "cache" / "run_abc.ndjson").exists()


def test_run_once__returns_none_when_no_run_id_in_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="oops, no run id here")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert _run_once(["some", "command"]) is None
