"""The TraceStore port: upsert events, maintain the run rollup, read both back.

Postgres (PostgresTraceStore) is the MVP implementation (ADR-003); an
in-memory fake (InMemoryTraceStore) implements the same Protocol for unit
tests. The query API (TRZ-P1-07) builds keyset pagination on top of
``list_runs``'s ``before`` param and ``get_events``'s ``after_seq`` param —
both are stable under concurrent inserts because they seek from an exact
row identity, never an OFFSET.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

from trazo_server.store.rows import DetectionRow, EventRow, RunRow


class TraceStore(Protocol):
    """Persistence port for runs and events."""

    async def ensure_project(self, project_id: str, name: str) -> None:
        """Insert the project if it doesn't exist yet; a no-op otherwise."""
        ...

    async def upsert_run(self, run: RunRow) -> None:
        """Insert-or-update one run row, keyed by run_id.

        Used both for the initial insert (on ``run.started``, where every
        field is taken as given) and for rollup updates (on ``run.finished``
        or a stale-run sweep) — but a rollup update only ever applies
        ``status``, ``finished_at``, and ``totals``. ``project_id``,
        ``framework``, ``started_at``, and ``tags`` are set once at
        creation and never overwritten by a later call, so callers doing a
        rollup-only update may pass placeholder values for those fields.
        """
        ...

    async def upsert_events(self, rows: Sequence[EventRow]) -> None:
        """Insert-or-update events, keyed by (run_id, seq) — idempotent:
        re-sending the same batch is a no-op beyond the first write."""
        ...

    async def get_run(self, run_id: str) -> RunRow | None:
        """Fetch one run by id, or None if it doesn't exist."""
        ...

    async def list_runs(
        self,
        *,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        before: tuple[datetime, str] | None = None,
    ) -> list[RunRow]:
        """List runs ordered by (started_at DESC, run_id DESC), optionally
        filtered by project and status.

        ``before``, if given, is the ``(started_at, run_id)`` of the last
        row a caller has already seen — only rows strictly after that
        position in the sort order are returned (keyset pagination).
        """
        ...

    async def get_events(
        self,
        run_id: str,
        *,
        kind: str | None = None,
        after_seq: int | None = None,
        limit: int = 100,
    ) -> list[EventRow]:
        """List one run's events in seq order, optionally filtered."""
        ...

    async def get_project_events(
        self,
        project_id: str,
        *,
        after_event_id: str | None = None,
        limit: int = 100,
    ) -> list[EventRow]:
        """List events across every run in a project, ordered by
        ``event_id`` (a ULID — globally unique and creation-time-sortable,
        unlike ``seq`` which only orders events within one run). Backs the
        live firehose (TRZ-P2-06), where ``after_event_id`` is the resume
        cursor.
        """
        ...

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
        """Atomically reserve the next seq for ``run_id`` and insert the
        resulting row; returns the assigned seq.

        The *only* legitimate way to mint a seq for an event discovered
        server-side (``detection.raised``, TRZ-P5-06) — every SDK-recorded
        event already carries its own seq, assigned client-side by the
        Recorder's own per-run counter (ARCHITECTURE.md's Policy-path
        note). A server-side discoverer has no access to that counter, so
        it must ask the store for the next one and insert atomically in
        the same transaction — reserving one without immediately writing
        it would leave a race window for a second concurrent detection on
        the same run to reserve the identical number.
        """
        ...

    async def insert_detection(self, detection: DetectionRow) -> None:
        """Insert one row into the ``detections`` projection table,
        idempotent on ``detection_id`` (a bus redelivery after a crash
        before ack must not duplicate the row)."""
        ...

    async def list_detections(self, run_id: str) -> list[DetectionRow]:
        """List one run's detections, most recently raised first."""
        ...
