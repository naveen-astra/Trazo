"""Unit tests for the corpus index archiver (TRZ-P3-05)."""

from __future__ import annotations

import json
from pathlib import Path

from archive_run import append_entry


def test_append_entry__creates_index_when_missing(tmp_path: Path) -> None:
    index_path = tmp_path / "index.json"

    entries = append_entry(
        index_path, run_id="run-1", project="research-assistant", framework="langgraph"
    )

    assert index_path.exists()
    assert entries == json.loads(index_path.read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0]["run_id"] == "run-1"
    assert entries[0]["project"] == "research-assistant"
    assert entries[0]["framework"] == "langgraph"
    assert "recorded_at" in entries[0]


def test_append_entry__appends_to_an_existing_index(tmp_path: Path) -> None:
    index_path = tmp_path / "index.json"
    append_entry(
        index_path, run_id="run-1", project="research-assistant", framework="langgraph"
    )

    entries = append_entry(
        index_path, run_id="run-2", project="content-pipeline", framework="crewai"
    )

    assert len(entries) == 2
    assert {e["run_id"] for e in entries} == {"run-1", "run-2"}


def test_append_entry__sorted_by_recorded_at(tmp_path: Path) -> None:
    index_path = tmp_path / "index.json"
    append_entry(index_path, run_id="run-1", project="p", framework="f")
    append_entry(index_path, run_id="run-2", project="p", framework="f")
    entries = append_entry(index_path, run_id="run-3", project="p", framework="f")

    timestamps = [e["recorded_at"] for e in entries]
    assert timestamps == sorted(timestamps)


def test_append_entry__creates_parent_directories(tmp_path: Path) -> None:
    index_path = tmp_path / "nested" / "dir" / "index.json"

    append_entry(index_path, run_id="run-1", project="p", framework="f")

    assert index_path.exists()
