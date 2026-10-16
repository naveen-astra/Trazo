"""Row value objects returned by TraceStore — plain data, no ORM identity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class RunRow:
    """One row of ``runs`` (DATABASE.md §2)."""

    run_id: str
    project_id: str
    framework: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    tags: dict[str, Any]
    totals: dict[str, Any]


@dataclass(frozen=True)
class EventRow:
    """One row of ``events`` (DATABASE.md §2); identity is (run_id, seq,
    sub_seq). ``sub_seq`` is 0 for every SDK event and 1, 2, ... for a
    server event attached after the SDK event at ``seq``."""

    run_id: str
    seq: int
    event_id: str
    kind: str
    ts: datetime
    step_id: str | None
    agent_id: str | None
    fingerprint: str | None
    payload: dict[str, Any]
    blobs: list[dict[str, Any]]
    sub_seq: int = 0


# Kinds only the control plane may originate. Ingest rejects them from
# clients, and the store worker never writes their event rows itself (the
# originating path already has, durably, before publishing).
SERVER_EVENT_KINDS: frozenset[str] = frozenset({"detection.raised", "policy.decision"})


@dataclass(frozen=True)
class AppendedEvent:
    """Where ``TraceStore.append_server_event`` recorded an event, and
    whether this call created it or found an earlier identical write."""

    seq: int
    sub_seq: int
    event_id: str
    created: bool


@dataclass(frozen=True)
class DetectionRow:
    """One row of ``detections`` (DATABASE.md §2) — the query-optimized
    projection of a ``detection.raised`` event, maintained by the store
    worker (TRZ-P5-06)."""

    detection_id: str
    run_id: str
    detector: str
    severity: str
    raised_at: datetime
    evidence: list[dict[str, Any]]
    details: dict[str, Any]


@dataclass(frozen=True)
class PolicyDecisionRow:
    """One row of ``policy_decisions`` (DATABASE.md §2) — the query-
    optimized projection of a ``policy.decision`` event, maintained by
    the store worker (TRZ-P6-05)."""

    decision_id: str
    run_id: str
    policy_id: str
    action_kind: str
    action_fp: str
    decision: str
    mode: str
    reasons: list[str]
    decided_at: datetime
    eval_ms: float


@dataclass(frozen=True)
class ReplayReportRow:
    """One row of ``replay_reports`` — the fidelity report ``trazo
    verify <run_id>`` computes, submitted by the SDK's CLI after a real
    replay against the run's own recorded history. Keyed by run_id and
    upserted: only the latest verification against the current code is
    meaningful, so re-verifying replaces rather than accumulates."""

    run_id: str
    boundary_fidelity: float
    state_fidelity: float
    matched: int
    reordered: int
    divergences: list[dict[str, Any]]
    replay_overhead: float | None
    verified_at: datetime
