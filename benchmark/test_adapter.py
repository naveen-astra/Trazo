"""Unit tests for the TrazoBench adapter interfaces (TRZ-P7-01)."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest
from adapter import RandomFlaggerAdapter, SubprocessReplayAdapter, TrazoDetectorAdapter

from trazo_server.events import Event, EventAdapter

_RUN_ID = "run_1"
_PROJECT = "research-assistant"


def _event(seq: int, kind: str, **overrides: Any) -> Event:
    envelope: dict[str, Any] = {
        "schema": "trazo.v1",
        "run_id": _RUN_ID,
        "project": _PROJECT,
        "seq": seq,
        "event_id": f"evt_{seq}",
        "kind": kind,
        "ts": "2026-01-01T00:00:00Z",
        "step_id": None,
        "agent_id": None,
        "fingerprint": None,
        "payload": {},
        "blobs": [],
    }
    envelope.update(overrides)
    return EventAdapter.validate_python(envelope)


def _tool_call(*, seq: int, fingerprint: str) -> Event:
    return _event(
        seq,
        "tool.call",
        fingerprint=fingerprint,
        payload={
            "tool_name": "web_search",
            "args": {},
            "result": "no results",
            "status": "ok",
            "latency_ms": 1.0,
            "side_effect_class": "external",
        },
    )


def test_trazo_detector_adapter__detect_returns_a_loop_detection() -> None:
    fp = "sha256:" + "a" * 64
    events = [_tool_call(seq=i * 5, fingerprint=fp) for i in range(4)]
    adapter = TrazoDetectorAdapter(run_id=_RUN_ID)

    detections = adapter.detect(events)

    assert [d.detector for d in detections] == ["loop"]
    # The triggering event (the last one to arrive) is last in evidence,
    # matching the fire-point-recovery contract adapter.py documents.
    assert detections[0].evidence_event_ids[-1] == "evt_15"


def test_trazo_detector_adapter__no_detections_when_nothing_repeats() -> None:
    events = [
        _tool_call(seq=i, fingerprint=f"sha256:{chr(97 + i) * 64}") for i in range(4)
    ]
    adapter = TrazoDetectorAdapter(run_id=_RUN_ID)

    assert adapter.detect(events) == []


def test_trazo_detector_adapter__sorts_events_by_seq_regardless_of_input_order() -> (
    None
):
    fp = "sha256:" + "a" * 64
    events = [_tool_call(seq=i * 5, fingerprint=fp) for i in range(4)]
    adapter = TrazoDetectorAdapter(run_id=_RUN_ID)

    assert adapter.detect(list(reversed(events))) == adapter.detect(events)


def _fp(seq: int) -> str:
    return f"sha256:{seq:064x}"


def test_random_flagger__deterministic_across_repeated_calls() -> None:
    events = [_tool_call(seq=i, fingerprint=_fp(i)) for i in range(200)]
    adapter = RandomFlaggerAdapter(flag_rate=0.1)

    first = adapter.detect(events)
    second = adapter.detect(events)

    assert [d.evidence_event_ids for d in first] == [
        d.evidence_event_ids for d in second
    ]


def test_random_flagger__flag_rate_zero_never_flags() -> None:
    events = [_tool_call(seq=i, fingerprint=_fp(i)) for i in range(50)]
    adapter = RandomFlaggerAdapter(flag_rate=0.0)

    assert adapter.detect(events) == []


def test_random_flagger__flag_rate_one_flags_every_boundary_event() -> None:
    events = [_tool_call(seq=i, fingerprint=_fp(i)) for i in range(10)]
    adapter = RandomFlaggerAdapter(flag_rate=1.0)

    assert len(adapter.detect(events)) == 10


def test_random_flagger__ignores_non_boundary_events() -> None:
    events = [
        _event(
            0,
            "run.started",
            payload={
                "framework": "langgraph",
                "framework_version": "1.0",
                "sdk_version": "0.1.0",
                "entry_input": {},
                "tags": {},
            },
        )
    ]
    adapter = RandomFlaggerAdapter(flag_rate=1.0)

    assert adapter.detect(events) == []


def test_random_flagger__rejects_out_of_range_flag_rate() -> None:
    with pytest.raises(ValueError):
        RandomFlaggerAdapter(flag_rate=1.5)


def test_subprocess_replay_adapter__parses_json_and_forwards_run_id_and_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_report = {
        "boundary_fidelity": 0.9,
        "state_fidelity": 0.8,
        "replay_overhead": 0.15,
        "divergences": [],
    }

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert command[:2] == ["uv", "run"]
        assert command[-4:] == ["run_1", "--endpoint", "http://example.test", "--json"]
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(fake_report))

    monkeypatch.setattr(subprocess, "run", fake_run)
    adapter = SubprocessReplayAdapter(["uv", "run", "some-entrypoint.py"])

    report = adapter.replay("run_1", endpoint="http://example.test")

    assert report == fake_report
