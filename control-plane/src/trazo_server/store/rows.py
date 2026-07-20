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
