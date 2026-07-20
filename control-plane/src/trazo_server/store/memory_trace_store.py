"""In-memory TraceStore fake: same Protocol as PostgresTraceStore, no DB needed.

Used by unit tests (this package's and the store worker's, TRZ-P1-06) that
need real upsert-on-(run_id, seq) semantics without a live Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from trazo_server.store.rows import EventRow, RunRow


class InMemoryTraceStore:
    """Implements trazo_server.store.trace_store.TraceStore over dicts."""

    def __init__(self) -> None:
        self._projects: dict[str, str] = {}
        self._runs: dict[str, RunRow] = {}
        # (run_id, seq) -> EventRow, keyed for the same idempotent-upsert
        # semantics as the real `events` table's PRIMARY KEY (run_id, seq).
        self._events: dict[tuple[str, int], EventRow] = {}

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
