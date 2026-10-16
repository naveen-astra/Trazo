"""Unit tests for trazo.core.replay_bundle (TRZ-P4-01)."""

from __future__ import annotations

import json

import pytest

from trazo.core.replay_bundle import InvalidBundleError, RecordedEvent, ReplayBundle

_MANIFEST = {
    "schema": "trazo.replay-bundle.v1",
    "run_id": "run_1",
    "project_id": "proj_1",
    "framework": "langgraph",
    "status": "ok",
    "started_at": "2026-01-01T00:00:00Z",
    "finished_at": "2026-01-01T00:00:05Z",
    "tags": {},
    "totals": {"events": 2},
    "blob_manifest": [],
}


def _event(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "run_id": "run_1",
        "seq": 0,
        "event_id": "evt_1",
        "kind": "run.started",
        "ts": "2026-01-01T00:00:00Z",
        "step_id": None,
        "agent_id": None,
        "fingerprint": None,
        "payload": {},
        "blobs": [],
    }
    defaults.update(overrides)
    return defaults


def _ndjson(
    manifest: dict[str, object],
    events: list[dict[str, object]],
    *,
    event_count: int | None = None,
) -> bytes:
    effective_manifest = {
        **manifest,
        "event_count": event_count if event_count is not None else len(events),
    }
    lines = [json.dumps(effective_manifest)] + [json.dumps(e) for e in events]
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_parse_ndjson__manifest_fields_round_trip() -> None:
    data = _ndjson(_MANIFEST, [_event(seq=0), _event(seq=1, kind="step.started")])

    bundle = ReplayBundle.parse_ndjson(data)

    assert bundle.run_id == "run_1"
    assert bundle.project_id == "proj_1"
    assert bundle.framework == "langgraph"
    assert bundle.status == "ok"
    assert bundle.event_count == 2
    assert len(bundle.events) == 2


def test_parse_ndjson__events_by_kind_preserves_seq_order() -> None:
    data = _ndjson(
        _MANIFEST,
        [
            _event(seq=0, kind="llm.call"),
            _event(seq=2, kind="llm.call"),
            _event(seq=1, kind="tool.call"),
        ],
    )

    bundle = ReplayBundle.parse_ndjson(data)

    assert [e.seq for e in bundle.events_by_kind("llm.call")] == [0, 2]
    assert [e.seq for e in bundle.events_by_kind("tool.call")] == [1]
    assert bundle.events_by_kind("memory.read") == []


def test_parse_ndjson__empty_bundle_raises() -> None:
    with pytest.raises(InvalidBundleError, match="empty bundle"):
        ReplayBundle.parse_ndjson(b"")


def test_parse_ndjson__unrecognized_schema_raises() -> None:
    bad_manifest = {**_MANIFEST, "schema": "something.else.v9"}
    data = _ndjson(bad_manifest, [])

    with pytest.raises(InvalidBundleError, match="unrecognized bundle schema"):
        ReplayBundle.parse_ndjson(data)


def test_parse_ndjson__event_count_mismatch_raises() -> None:
    data = _ndjson(_MANIFEST, [_event(seq=0)], event_count=5)

    with pytest.raises(InvalidBundleError, match="manifest declares 5"):
        ReplayBundle.parse_ndjson(data)


def test_recorded_event__reads_sub_seq_and_defaults_it_for_older_bundles() -> None:
    base = {
        "run_id": "run_1",
        "seq": 3,
        "event_id": "evt_1",
        "kind": "detection.raised",
        "ts": "2026-01-01T00:00:00Z",
        "payload": {},
    }

    assert RecordedEvent.from_dict({**base, "sub_seq": 2}).sub_seq == 2
    assert RecordedEvent.from_dict(base).sub_seq == 0
