"""Unit tests for trazo.core.recorder.Recorder (TRZ-P2-03).

Uses a fake Shipper (records enqueued envelopes; no thread, no network) so
these tests isolate the Recorder's own envelope-building, fingerprinting,
and context-reading logic. Shipper's own behavior is covered in
test_shipper.py.
"""

from __future__ import annotations

from typing import Any

import pytest

from trazo.core.context import agent_scope, run_scope, step_scope
from trazo.core.recorder import Recorder, RecorderMode
from trazo.errors import NoActiveRunError


class _FakeShipper:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []

    def enqueue(self, event: dict[str, Any]) -> None:
        self.enqueued.append(event)

    def flush_and_stop(self, *, timeout: float = 5.0) -> None:
        pass


def test_emit__requires_an_active_run() -> None:
    recorder = Recorder(shipper=_FakeShipper())
    with pytest.raises(NoActiveRunError):
        recorder.emit("sdk.diagnostic", {"level": "info", "message": "hi"})


def test_emit__builds_a_schema_valid_envelope() -> None:
    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)

    with run_scope("research-assistant") as ctx:
        recorder.emit("sdk.diagnostic", {"level": "info", "message": "hi"})

    [event] = shipper.enqueued
    assert event["schema"] == "trazo.v1"
    assert event["run_id"] == ctx.run_id
    assert event["project"] == "research-assistant"
    assert event["seq"] == 0
    assert event["kind"] == "sdk.diagnostic"
    assert event["payload"] == {"level": "info", "message": "hi"}
    assert event["event_id"].startswith("evt_")
    assert "step_id" not in event
    assert "agent_id" not in event
    assert "fingerprint" not in event


def test_emit__seq_increments_across_events_in_one_run() -> None:
    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)

    with run_scope("proj"):
        recorder.emit("run.started", {})
        recorder.emit("sdk.diagnostic", {"level": "info", "message": "x"})

    assert [e["seq"] for e in shipper.enqueued] == [0, 1]


def test_emit__includes_step_id_and_agent_id_when_in_scope() -> None:
    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)

    with run_scope("proj"), step_scope("stp_1") as step_id, agent_scope("researcher"):
        recorder.emit("sdk.diagnostic", {"level": "info", "message": "x"})

    [event] = shipper.enqueued
    assert event["step_id"] == step_id
    assert event["agent_id"] == "researcher"


def test_emit__redacts_sensitive_payload_fields() -> None:
    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)

    with run_scope("proj"):
        recorder.emit("tool.call", {"tool_name": "auth", "args": {"password": "x"}})

    [event] = shipper.enqueued
    assert event["payload"]["args"]["password"] == "***REDACTED***"


def test_boundary__executes_and_merges_inputs_with_result() -> None:
    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)

    with run_scope("proj"):
        result = recorder.boundary(
            "tool.call",
            {
                "tool_name": "web_search",
                "args": {"q": "hi"},
                "side_effect_class": "external",
            },
            lambda: {"result": {"hits": []}, "status": "ok", "latency_ms": 12},
        )

    assert result == {"result": {"hits": []}, "status": "ok", "latency_ms": 12}
    [event] = shipper.enqueued
    assert event["payload"]["tool_name"] == "web_search"
    assert event["payload"]["status"] == "ok"


def test_boundary__attaches_fingerprint_for_fingerprinted_kinds() -> None:
    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)

    with run_scope("proj"):
        recorder.boundary(
            "tool.call",
            {
                "tool_name": "web_search",
                "args": {"q": "hi"},
                "side_effect_class": "external",
            },
            lambda: {"result": "r", "status": "ok", "latency_ms": 1},
        )

    [event] = shipper.enqueued
    assert event["fingerprint"].startswith("sha256:")


def test_boundary__omits_fingerprint_for_non_fingerprinted_kinds() -> None:
    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)

    with run_scope("proj"):
        recorder.boundary(
            "agent.message", {"from_agent": "a", "to_agent": "b"}, lambda: {}
        )

    [event] = shipper.enqueued
    assert "fingerprint" not in event


def test_boundary__exception_propagates_and_nothing_is_recorded() -> None:
    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)

    def _fails() -> dict[str, Any]:
        raise RuntimeError("boom")

    with run_scope("proj"), pytest.raises(RuntimeError, match="boom"):
        recorder.boundary("tool.call", {"tool_name": "x", "args": {}}, _fails)

    assert shipper.enqueued == []


def test_boundary__replay_mode_raises_not_implemented() -> None:
    recorder = Recorder(shipper=_FakeShipper(), mode=RecorderMode.REPLAY)

    with run_scope("proj"), pytest.raises(NotImplementedError, match="Phase 4"):
        recorder.boundary("tool.call", {"tool_name": "x", "args": {}}, lambda: {})
