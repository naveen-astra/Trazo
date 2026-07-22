"""Unit tests for trazo.core.spool.DiskSpool (TRZ-P2-03)."""

from __future__ import annotations

from pathlib import Path

import pytest

from trazo.core.spool import DiskSpool, max_bytes_from_env


def test_spool__write_then_drain_round_trips_events(tmp_path: Path) -> None:
    spool = DiskSpool(tmp_path)
    events = [{"seq": 0, "kind": "run.started"}, {"seq": 1, "kind": "llm.call"}]

    assert spool.write(events) is True

    [(path, drained)] = spool.drain()
    assert drained == events
    assert path.parent == tmp_path


def test_spool__remove_deletes_the_batch_file(tmp_path: Path) -> None:
    spool = DiskSpool(tmp_path)
    spool.write([{"a": 1}])
    [(path, _)] = spool.drain()

    spool.remove(path)

    assert spool.drain() == []
    assert spool.pending_batch_count() == 0


def test_spool__multiple_batches_drain_oldest_first(tmp_path: Path) -> None:
    spool = DiskSpool(tmp_path)
    spool.write([{"batch": 1}])
    spool.write([{"batch": 2}])
    spool.write([{"batch": 3}])

    drained = spool.drain()

    assert [events[0]["batch"] for _path, events in drained] == [1, 2, 3]


def test_spool__empty_batch_is_a_no_op(tmp_path: Path) -> None:
    spool = DiskSpool(tmp_path)

    assert spool.write([]) is False
    assert spool.pending_batch_count() == 0


def test_spool__refuses_to_write_past_max_bytes(tmp_path: Path) -> None:
    spool = DiskSpool(tmp_path, max_bytes=10)  # tiny budget
    first_ok = spool.write([{"padding": "x" * 50}])
    assert first_ok is True  # first write always allowed even if it exceeds budget

    assert spool.is_full() is True
    second_ok = spool.write([{"more": "data"}])
    assert second_ok is False  # dropped: spool already over budget


def test_spool__pending_batch_count_reflects_undrained_batches(tmp_path: Path) -> None:
    spool = DiskSpool(tmp_path)
    assert spool.pending_batch_count() == 0

    spool.write([{"a": 1}])
    spool.write([{"b": 2}])

    assert spool.pending_batch_count() == 2


def test_max_bytes_from_env__defaults_to_256mb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TRAZO_SPOOL_MAX_MB", raising=False)

    assert max_bytes_from_env() == 256 * 1024 * 1024


def test_max_bytes_from_env__honors_the_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRAZO_SPOOL_MAX_MB", "1")

    assert max_bytes_from_env() == 1024 * 1024
