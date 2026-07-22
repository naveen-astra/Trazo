"""Unit tests for trazo.core.ulid (TRZ-P2-01)."""

from __future__ import annotations

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


def test_ulid__prefixed_helpers_use_the_documented_prefixes() -> None:
    assert new_run_id().startswith("run_")
    assert new_event_id().startswith("evt_")
    assert new_step_id().startswith("stp_")
