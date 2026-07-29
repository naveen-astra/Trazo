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
    """One row of ``events`` (DATABASE.md §2); identity is (run_id, seq)."""

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
