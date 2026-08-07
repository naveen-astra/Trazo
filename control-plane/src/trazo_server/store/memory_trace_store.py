"""In-memory TraceStore fake: same Protocol as PostgresTraceStore, no DB needed.

Used by unit tests (this package's and the store worker's, TRZ-P1-06) that
need real upsert-on-(run_id, seq) semantics without a live Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any

from trazo_server.store.rows import DetectionRow, EventRow, PolicyDecisionRow, RunRow


class InMemoryTraceStore:
    """Implements trazo_server.store.trace_store.TraceStore over dicts."""

    def __init__(self) -> None:
        self._projects: dict[str, str] = {}
        self._runs: dict[str, RunRow] = {}
        # (run_id, seq) -> EventRow, keyed for the same idempotent-upsert
        # semantics as the real `events` table's PRIMARY KEY (run_id, seq).
        self._events: dict[tuple[str, int], EventRow] = {}
        self._detections: dict[str, DetectionRow] = {}
        self._policy_decisions: dict[str, PolicyDecisionRow] = {}

    async def list_project_names(self) -> dict[str, str]:
        return dict(self._projects)

    async def ensure_project(self, project_id: str, name: str) -> None:
        self._projects.setdefault(project_id, name)

    async def upsert_run(self, run: RunRow) -> None:
        # Mirrors PostgresTraceStore's ON CONFLICT semantics: run_id/
        # project_id/framework/started_at/tags are set once at creation;
        # only status/finished_at/totals are legitimate rollup updates
        # (DATABASE.md §2) — see that store's upsert_run for why.
        existing = self._runs.get(run.run_id)
        if existing is None:
            self._runs[run.run_id] = run
            return
        self._runs[run.run_id] = replace(
            existing,
            status=run.status,
            finished_at=run.finished_at,
            totals=run.totals,
        )

    async def upsert_events(self, rows: Sequence[EventRow]) -> None:
        for row in rows:
            self._events[(row.run_id, row.seq)] = row

    async def get_run(self, run_id: str) -> RunRow | None:
        return self._runs.get(run_id)

    async def list_runs(
        self,
        *,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        before: tuple[datetime, str] | None = None,
    ) -> list[RunRow]:
        rows = [
            run
            for run in self._runs.values()
            if (project_id is None or run.project_id == project_id)
            and (status is None or run.status == status)
        ]
        rows.sort(key=lambda run: (run.started_at, run.run_id), reverse=True)
        if before is not None:
            rows = [run for run in rows if (run.started_at, run.run_id) < before]
        return rows[:limit]

    async def get_events(
        self,
        run_id: str,
        *,
        kind: str | None = None,
        after_seq: int | None = None,
        limit: int = 100,
    ) -> list[EventRow]:
        rows = [
            event
            for (event_run_id, _seq), event in self._events.items()
            if event_run_id == run_id
            and (kind is None or event.kind == kind)
            and (after_seq is None or event.seq > after_seq)
        ]
        rows.sort(key=lambda event: event.seq)
        return rows[:limit]

    async def get_project_events(
        self,
        project_id: str | None,
        *,
        after_event_id: str | None = None,
        limit: int = 100,
    ) -> list[EventRow]:
        run_ids_in_project = (
            None
            if project_id is None
            else {
                run.run_id
                for run in self._runs.values()
                if run.project_id == project_id
            }
        )
        rows = [
            event
            for (event_run_id, _seq), event in self._events.items()
            if (run_ids_in_project is None or event_run_id in run_ids_in_project)
            and (after_event_id is None or event.event_id > after_event_id)
        ]
        rows.sort(key=lambda event: event.event_id)
        return rows[:limit]

    async def latest_event_id(self, project_id: str | None) -> str | None:
        run_ids_in_project = (
            None
            if project_id is None
            else {
                run.run_id
                for run in self._runs.values()
                if run.project_id == project_id
            }
        )
        event_ids = [
            event.event_id
            for (event_run_id, _seq), event in self._events.items()
            if run_ids_in_project is None or event_run_id in run_ids_in_project
        ]
        return max(event_ids) if event_ids else None

    async def append_event(
        self,
        *,
        run_id: str,
        event_id: str,
        kind: str,
        ts: datetime,
        fingerprint: str | None,
        payload: dict[str, Any],
    ) -> int:
        # No real concurrency in a single-threaded event loop test fake:
        # this "reservation" is just the current max + 1, computed and
        # applied in one uninterrupted (no `await` in between) step.
        existing_seqs = [seq for (rid, seq) in self._events if rid == run_id]
        next_seq = max(existing_seqs, default=-1) + 1
        self._events[(run_id, next_seq)] = EventRow(
            run_id=run_id,
            seq=next_seq,
            event_id=event_id,
            kind=kind,
            ts=ts,
            step_id=None,
            agent_id=None,
            fingerprint=fingerprint,
            payload=payload,
            blobs=[],
        )
        return next_seq

    async def insert_detection(self, detection: DetectionRow) -> None:
        self._detections.setdefault(detection.detection_id, detection)

    async def list_detections(self, run_id: str) -> list[DetectionRow]:
        rows = [d for d in self._detections.values() if d.run_id == run_id]
        rows.sort(key=lambda d: d.raised_at, reverse=True)
        return rows

    async def insert_policy_decision(self, decision: PolicyDecisionRow) -> None:
        self._policy_decisions.setdefault(decision.decision_id, decision)

    async def list_policy_decisions(self, run_id: str) -> list[PolicyDecisionRow]:
        rows = [d for d in self._policy_decisions.values() if d.run_id == run_id]
        rows.sort(key=lambda d: d.decided_at, reverse=True)
        return rows

    async def list_recent_detections(self, *, limit: int) -> list[DetectionRow]:
        rows = sorted(
            self._detections.values(), key=lambda d: d.raised_at, reverse=True
        )
        return rows[:limit]

    async def list_recent_policy_decisions(
        self, *, limit: int
    ) -> list[PolicyDecisionRow]:
        rows = sorted(
            self._policy_decisions.values(), key=lambda d: d.decided_at, reverse=True
        )
        return rows[:limit]

    async def list_recent_events(
        self, *, kind: str | None = None, limit: int
    ) -> list[EventRow]:
        rows = [
            event
            for event in self._events.values()
            if kind is None or event.kind == kind
        ]
        # event_id breaks ts ties. Fast agents emit many events inside one
        # millisecond, and ts alone left the feed showing a run's events
        # shuffled (…54, 52, 53, 50, 51…). event_id is a ULID, monotonic
        # within a run, so it restores true emission order.
        rows.sort(key=lambda e: (e.ts, e.event_id), reverse=True)
        return rows[:limit]
