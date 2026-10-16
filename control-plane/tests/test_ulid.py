"""Unit tests for trazo_server.ulid (TRZ-P5-06)."""

from __future__ import annotations

import pytest

from trazo_server.ulid import new_detection_id, new_event_id, new_ulid

_CROCKFORD_CHARS = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")


def test_ulid__has_correct_length_and_alphabet() -> None:
    ulid = new_ulid()
    assert len(ulid) == 26
    assert set(ulid) <= _CROCKFORD_CHARS


def test_ulid__sorts_lexically_by_creation_time() -> None:
    base = 1_700_000_000_000
    ulids = [new_ulid(timestamp_ms=base + i) for i in range(10)]
    assert ulids == sorted(ulids)


def test_ulid__two_calls_at_same_timestamp_differ() -> None:
    ts = 1_700_000_000_000
    a = new_ulid(timestamp_ms=ts)
    b = new_ulid(timestamp_ms=ts)
    assert a != b  # random component differs


def test_ulid__is_monotonic_within_one_millisecond() -> None:
    """These ``evt_`` ids share the ``events`` table and the firehose with
    the SDK's, and the firehose pages with ``WHERE event_id > cursor`` —
    so an id sorting below an already-passed cursor is dropped from the
    live stream for good. Ordering has to be total, not
    millisecond-granular. Mirrors the SDK copy's test of the same name.
    """
    ts = 1_700_000_000_000
    ulids = [new_ulid(timestamp_ms=ts) for _ in range(500)]

    assert ulids == sorted(ulids)
    assert len(set(ulids)) == len(ulids)


def test_ulid__real_clock_generation_is_monotonic() -> None:
    ulids = [new_ulid() for _ in range(2000)]

    assert ulids == sorted(ulids)
    assert len(set(ulids)) == len(ulids)


def test_ulid__prefixed_helpers_use_the_documented_prefixes() -> None:
    assert new_event_id().startswith("evt_")
    assert new_detection_id().startswith("det_")


def test_ulid__stays_monotonic_when_the_clock_reads_earlier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Server-minted event ids land in the same events table the firehose
    pages with `WHERE event_id > cursor`; an id that sorted below one
    already issued would be skipped from the live stream for good. A clock
    reading that comes out earlier -- another thread minting in between,
    or an NTP step back -- used to produce exactly that."""
    import trazo_server.ulid as ulid_module

    clock = iter([1_000.002, 1_000.001])  # the second reading is earlier
    monkeypatch.setattr(ulid_module.time, "time", lambda: next(clock))

    first = new_ulid()
    second = new_ulid()

    assert second > first


def test_ulid__concurrent_generation_stays_unique_and_globally_ordered() -> None:
    import threading

    issued: list[str] = []
    lock = threading.Lock()

    def mint() -> None:
        for _ in range(500):
            with lock:
                issued.append(new_ulid())

    threads = [threading.Thread(target=mint) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(set(issued)) == len(issued)
    # Appended under the same lock that orders issue, so issue order is the
    # list order -- and ids must sort exactly that way.
    assert issued == sorted(issued)
