"""Unit tests for the spool-to-bundle converter (TRZ-P4-08)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from spool_to_bundle import NoRunStartedError, build_bundle_ndjson, write_bundle_cache


def _event(seq: int, kind: str, **overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "run_id": "run_1",
        "project": "proj_1",
        "seq": seq,
        "event_id": f"evt_{seq}",
        "kind": kind,
        "ts": "2026-01-01T00:00:00Z",
        "payload": {},
    }
    defaults.update(overrides)
    return defaults


def test_build_bundle_ndjson__manifest_from_run_started_and_finished() -> None:
    events = [
        _event(0, "run.started", payload={"framework": "langgraph", "tags": {"x": 1}}),
        _event(1, "llm.call", payload={"response": "hi"}),
        _event(2, "run.finished", payload={"totals": {"events": 3}}),
    ]

    data = build_bundle_ndjson(events, run_id="run_1")

    lines = data.decode("utf-8").strip("\n").split("\n")
    manifest = json.loads(lines[0])
    assert manifest["schema"] == "trazo.replay-bundle.v1"
    assert manifest["framework"] == "langgraph"
    assert manifest["tags"] == {"x": 1}
    assert manifest["status"] == "ok"
    assert manifest["totals"] == {"events": 3}
    assert manifest["event_count"] == 3
    assert len(lines) == 4  # manifest + 3 events


def test_build_bundle_ndjson__status_running_when_no_run_finished() -> None:
    events = [_event(0, "run.started", payload={"framework": "crewai"})]

    data = build_bundle_ndjson(events, run_id="run_1")

    manifest = json.loads(data.decode("utf-8").split("\n")[0])
    assert manifest["status"] == "running"
    assert manifest["finished_at"] is None


def test_build_bundle_ndjson__raises_without_a_run_started_event() -> None:
    events = [_event(0, "llm.call", payload={})]

    with pytest.raises(NoRunStartedError):
        build_bundle_ndjson(events, run_id="run_1")


def test_write_bundle_cache__reads_multiple_spool_files_filters_by_run_id(
    tmp_path: Path,
) -> None:
    spool_dir = tmp_path / "spool"
    spool_dir.mkdir()
    (spool_dir / "batch1.ndjson").write_text(
        json.dumps(_event(0, "run.started", payload={"framework": "langgraph"}))
        + "\n"
        + json.dumps(
            _event(0, "run.started", run_id="run_OTHER", payload={"framework": "x"})
        )
        + "\n",
        encoding="utf-8",
    )
    (spool_dir / "batch2.ndjson").write_text(
        json.dumps(_event(1, "run.finished", payload={"totals": {}})) + "\n",
        encoding="utf-8",
    )
    cache_dir = tmp_path / "cache"

    cache_path = write_bundle_cache(
        spool_dir=spool_dir, cache_dir=cache_dir, run_id="run_1"
    )

    assert cache_path == cache_dir / "run_1.ndjson"
    manifest = json.loads(cache_path.read_text(encoding="utf-8").split("\n")[0])
    assert manifest["event_count"] == 2  # run_OTHER's event excluded


def test_write_bundle_cache__events_are_seq_ordered_regardless_of_file_order(
    tmp_path: Path,
) -> None:
    spool_dir = tmp_path / "spool"
    spool_dir.mkdir()
    # Written out of seq order across two files, oldest-file-first drain
    # order still shouldn't matter since we sort by seq explicitly.
    (spool_dir / "a.ndjson").write_text(
        json.dumps(_event(2, "step.finished")) + "\n", encoding="utf-8"
    )
    (spool_dir / "b.ndjson").write_text(
        json.dumps(_event(0, "run.started", payload={"framework": "langgraph"}))
        + "\n"
        + json.dumps(_event(1, "step.started"))
        + "\n",
        encoding="utf-8",
    )
    cache_dir = tmp_path / "cache"

    cache_path = write_bundle_cache(
        spool_dir=spool_dir, cache_dir=cache_dir, run_id="run_1"
    )

    lines = cache_path.read_text(encoding="utf-8").strip("\n").split("\n")
    events = [json.loads(line) for line in lines[1:]]
    assert [e["seq"] for e in events] == [0, 1, 2]
