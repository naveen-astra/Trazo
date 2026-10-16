"""Unit tests for trazo.core.ulid (TRZ-P2-01)."""

from __future__ import annotations

import pytest

from trazo.core.ulid import (
    new_event_id,
    new_run_id,
    new_step_id,
    new_ulid,
    ulid_timestamp_ms,
)

_CROCKFORD_CHARS = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")


def test_ulid__has_correct_length_and_alphabet() -> None:
    ulid = new_ulid()
    assert len(ulid) == 26
    assert set(ulid) <= _CROCKFORD_CHARS


def test_ulid__timestamp_round_trips() -> None:
    ts = 1_700_000_000_123
    ulid = new_ulid(timestamp_ms=ts)
    assert ulid_timestamp_ms(ulid) == ts


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
    """Real bug this pins (TRZ-P5-01): with a fresh random per id, ids
    minted in the same millisecond sorted *randomly*, so "sortable by
    creation time" only held at millisecond granularity. An instrumented
    agent emits dozens of events per millisecond, which showed up as a
    run's events shuffled in the Traces feed — and, more seriously, the
    live firehose pages with ``WHERE event_id > cursor``, so an event
    whose id sorted below an already-passed cursor was dropped from the
    stream for good.
    """
    ts = 1_700_000_000_000
    ulids = [new_ulid(timestamp_ms=ts) for _ in range(500)]

    assert ulids == sorted(ulids)
    assert len(set(ulids)) == len(ulids)


def test_ulid__real_clock_generation_is_monotonic() -> None:
    """Same guarantee without an injected timestamp — this is the path
    that actually mints event ids, and a tight loop here genuinely lands
    many ids inside one millisecond."""
    ulids = [new_ulid() for _ in range(2000)]

    assert ulids == sorted(ulids)
    assert len(set(ulids)) == len(ulids)


def test_ulid__concurrent_generation_stays_unique_and_ordered_per_thread() -> None:
    """The counter is shared mutable state and events are emitted from
    whatever thread the agent runs on, so minting must be thread-safe."""
    import threading

    results: list[list[str]] = []
    lock = threading.Lock()

    def mint() -> None:
        batch = [new_ulid() for _ in range(500)]
        with lock:
            results.append(batch)

    threads = [threading.Thread(target=mint) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    every_id = [ulid for batch in results for ulid in batch]
    assert len(set(every_id)) == len(every_id)
    # Each thread's own ids stay in issue order even when interleaved.
    for batch in results:
        assert batch == sorted(batch)


def test_ulid__prefixed_helpers_use_the_documented_prefixes() -> None:
    assert new_run_id().startswith("run_")
    assert new_event_id().startswith("evt_")
    assert new_step_id().startswith("stp_")


def test_ulid__stays_monotonic_when_the_clock_reads_earlier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: the clock used to be read before taking the lock, and a
    different millisecond from the last one issued redrew the random part.
    A reading that came out *earlier* -- another thread having minted in
    the next millisecond in between, or an NTP step back -- then produced
    an id sorting below ones already issued. Seen on CI as a per-thread
    ordering failure; it also matters live, where the firehose pages on
    event_id and would skip such an id for good."""
    import trazo.core.ulid as ulid_module

    clock = iter([1_000.002, 1_000.001])  # the second reading is earlier
    monkeypatch.setattr(ulid_module.time, "time", lambda: next(clock))

    first = new_ulid()
    second = new_ulid()

    assert second > first
    assert ulid_timestamp_ms(second) == ulid_timestamp_ms(first)
