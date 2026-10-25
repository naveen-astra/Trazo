"""In-memory TraceStore fake: same Protocol as PostgresTraceStore, no DB needed.

Used by unit tests (this package's and the store worker's, TRZ-P1-06) that
need real upsert-on-(run_id, seq) semantics without a live Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any

from trazo_server.project_id import derive_project_id
from trazo_server.store.rows import (
    AppendedEvent,
    DetectionRow,
    EventRow,
    PolicyDecisionRow,
    ReplayReportRow,
    RunRow,
)


class InMemoryTraceStore:
    """Implements trazo_server.store.trace_store.TraceStore over dicts."""

    def __init__(self) -> None:
        self._projects: dict[str, str] = {}
        self._runs: dict[str, RunRow] = {}
        # (run_id, seq) -> EventRow, keyed for the same idempotent-upsert
        # semantics as the real `events` table's PRIMARY KEY (run_id, seq).
        # Keyed like the real table's primary key: (run_id, seq, sub_seq).
        self._events: dict[tuple[str, int, int], EventRow] = {}
        self._idempotency: dict[tuple[str, str], tuple[int, int]] = {}
        self._next_ingest_seq = 1
        self._detections: dict[str, DetectionRow] = {}
        self._policy_decisions: dict[str, PolicyDecisionRow] = {}
        self._replay_reports: dict[str, ReplayReportRow] = {}

    def _store_event(self, row: EventRow) -> None:
        """Mirror Postgres: a new row is numbered on insert; an upsert onto
        an existing row keeps that row's number. A non-zero ingest_seq on
        the incoming row is honoured, so a test can stand in for a commit
        that lands out of order."""
        key = (row.run_id, row.seq, row.sub_seq)
        existing = self._events.get(key)
        if row.ingest_seq:
            ingest_seq = row.ingest_seq
            self._next_ingest_seq = max(self._next_ingest_seq, ingest_seq + 1)
        elif existing is not None:
            ingest_seq = existing.ingest_seq
        else:
            ingest_seq = self._next_ingest_seq
            self._next_ingest_seq += 1
        self._events[key] = replace(row, ingest_seq=ingest_seq)

    async def list_project_names(self) -> dict[str, str]:
        return dict(self._projects)

    async def ensure_project(self, project_id: str, name: str) -> None:
        self._projects.setdefault(project_id, name)

    async def upsert_run(self, run: RunRow, *, authoritative: bool = False) -> None:
        # Mirrors PostgresTraceStore's ON CONFLICT semantics: run_id/
        # project_id/framework/started_at/tags are set once at creation;
        # only status/finished_at/totals are legitimate rollup updates
        # (DATABASE.md §2) — see that store's upsert_run for why, including
        # what `authoritative` reclaims.
        existing = self._runs.get(run.run_id)
        if existing is None or authoritative:
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
            self._store_event(row)

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
        after_sub_seq: int | None = None,
        limit: int = 100,
    ) -> list[EventRow]:
        def after_cursor(event: EventRow) -> bool:
            if after_seq is None:
                return True
            if after_sub_seq is None:
                return event.seq > after_seq
            return (event.seq, event.sub_seq) > (after_seq, after_sub_seq)

        rows = [
            event
            for (event_run_id, _seq, _sub), event in self._events.items()
            if event_run_id == run_id
            and (kind is None or event.kind == kind)
            and after_cursor(event)
        ]
        rows.sort(key=lambda event: (event.seq, event.sub_seq))
        return rows[:limit]

    async def get_server_events(self, run_id: str) -> list[EventRow]:
        rows = [
            event
            for (event_run_id, _seq, sub), event in self._events.items()
            if event_run_id == run_id and sub > 0
        ]
        rows.sort(key=lambda event: (event.seq, event.sub_seq))
        return rows

    async def get_project_events(
        self,
        project_id: str | None,
        *,
        after_ingest_seq: int | None = None,
        exclude_ingest_seqs: frozenset[int] = frozenset(),
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
            for (event_run_id, _seq, _sub), event in self._events.items()
            if (run_ids_in_project is None or event_run_id in run_ids_in_project)
            and (after_ingest_seq is None or event.ingest_seq > after_ingest_seq)
            and event.ingest_seq not in exclude_ingest_seqs
        ]
        rows.sort(key=lambda event: event.ingest_seq)
        return rows[:limit]

    async def latest_ingest_seq(self, project_id: str | None) -> int | None:
        rows = await self.get_project_events(project_id, limit=len(self._events) + 1)
        return rows[-1].ingest_seq if rows else None

    async def append_server_event(
        self,
        *,
        run_id: str,
        project: str,
        after_seq: int | None,
        event_id: str,
        kind: str,
        ts: datetime,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> AppendedEvent:
        # Mirrors PostgresTraceStore.append_server_event; single-threaded,
        # so no lock is needed between the reads and the write below.
        project_id = derive_project_id(project)
        self._projects.setdefault(project_id, project)
        if run_id not in self._runs:
            self._runs[run_id] = RunRow(
                run_id=run_id,
                project_id=project_id,
                framework="unknown",
                status="running",
                started_at=ts,
                finished_at=None,
                tags={},
                totals={},
            )
        if idempotency_key is not None:
            position = self._idempotency.get((run_id, idempotency_key))
            if position is not None:
                existing = self._events[(run_id, *position)]
                return AppendedEvent(
                    seq=existing.seq,
                    sub_seq=existing.sub_seq,
                    event_id=existing.event_id,
                    created=False,
                )

        anchor = after_seq
        if anchor is None:
            anchor = max(
                (seq for (rid, seq, sub) in self._events if rid == run_id and sub == 0),
                default=0,
            )
        anchor = max(anchor, 0)
        sub_seq = (
            max(
                (
                    sub
                    for (rid, seq, sub) in self._events
                    if rid == run_id and seq == anchor
                ),
                default=0,
            )
            + 1
        )
        self._store_event(
            EventRow(
                run_id=run_id,
                seq=anchor,
                event_id=event_id,
                kind=kind,
                ts=ts,
                step_id=None,
                agent_id=None,
                fingerprint=None,
                payload=payload,
                blobs=[],
                sub_seq=sub_seq,
            )
        )
        if idempotency_key is not None:
            self._idempotency[(run_id, idempotency_key)] = (anchor, sub_seq)
        return AppendedEvent(
            seq=anchor, sub_seq=sub_seq, event_id=event_id, created=True
        )

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

    async def upsert_replay_report(self, report: ReplayReportRow) -> None:
        self._replay_reports[report.run_id] = report

    async def get_replay_report(self, run_id: str) -> ReplayReportRow | None:
        return self._replay_reports.get(run_id)
