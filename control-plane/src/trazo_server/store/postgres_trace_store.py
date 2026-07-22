"""PostgresTraceStore: the MVP TraceStore implementation (ADR-003)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from trazo_server.store.models import events, projects, runs
from trazo_server.store.rows import EventRow, RunRow


class PostgresTraceStore:
    """Implements trazo_server.store.trace_store.TraceStore over Postgres."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def ensure_project(self, project_id: str, name: str) -> None:
        stmt = (
            pg_insert(projects)
            .values(project_id=project_id, name=name)
            .on_conflict_do_nothing(index_elements=[projects.c.project_id])
        )
        async with self._engine.begin() as conn:
            await conn.execute(stmt)

    async def upsert_run(self, run: RunRow) -> None:
        # run_id/project_id/framework/started_at/tags are set once, at
        # creation; only status/finished_at/totals are legitimate rollup
        # updates (DATABASE.md §2). A caller updating an existing run does
        # not need to know the original tags — passing any value for the
        # fields below on a conflict is safe because they're never applied.
        insert_stmt = pg_insert(runs).values(
            run_id=run.run_id,
            project_id=run.project_id,
            framework=run.framework,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            tags=run.tags,
            totals=run.totals,
        )
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=[runs.c.run_id],
            set_={
                "status": insert_stmt.excluded.status,
                "finished_at": insert_stmt.excluded.finished_at,
                "totals": insert_stmt.excluded.totals,
            },
        )
        async with self._engine.begin() as conn:
            await conn.execute(stmt)

    async def upsert_events(self, rows: Sequence[EventRow]) -> None:
        if not rows:
            return
        values: list[dict[str, Any]] = [
            {
                "run_id": row.run_id,
                "seq": row.seq,
                "event_id": row.event_id,
                "kind": row.kind,
                "ts": row.ts,
                "step_id": row.step_id,
                "agent_id": row.agent_id,
                "fingerprint": row.fingerprint,
                "payload": row.payload,
                "blobs": row.blobs,
            }
            for row in rows
        ]
        insert_stmt = pg_insert(events).values(values)
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=[events.c.run_id, events.c.seq],
            set_={
                "event_id": insert_stmt.excluded.event_id,
                "kind": insert_stmt.excluded.kind,
                "ts": insert_stmt.excluded.ts,
                "step_id": insert_stmt.excluded.step_id,
                "agent_id": insert_stmt.excluded.agent_id,
                "fingerprint": insert_stmt.excluded.fingerprint,
                "payload": insert_stmt.excluded.payload,
                "blobs": insert_stmt.excluded.blobs,
            },
        )
        async with self._engine.begin() as conn:
            await conn.execute(stmt)

    async def get_run(self, run_id: str) -> RunRow | None:
        stmt = sa.select(runs).where(runs.c.run_id == run_id)
        async with self._engine.connect() as conn:
            result = await conn.execute(stmt)
            row = result.mappings().one_or_none()
        return None if row is None else _run_row_from_mapping(row)

    async def list_runs(
        self,
        *,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        before: tuple[datetime, str] | None = None,
    ) -> list[RunRow]:
        stmt = (
            sa.select(runs)
            .order_by(runs.c.started_at.desc(), runs.c.run_id.desc())
            .limit(limit)
        )
        if project_id is not None:
            stmt = stmt.where(runs.c.project_id == project_id)
        if status is not None:
            stmt = stmt.where(runs.c.status == status)
        if before is not None:
            before_started_at, before_run_id = before
            # Row-wise comparison: correct keyset seek on a compound sort
            # key, stable under concurrent inserts (unlike OFFSET).
            stmt = stmt.where(
                sa.tuple_(runs.c.started_at, runs.c.run_id)
                < sa.tuple_(sa.literal(before_started_at), sa.literal(before_run_id))
            )
        async with self._engine.connect() as conn:
            result = await conn.execute(stmt)
            fetched = result.mappings().all()
        return [_run_row_from_mapping(row) for row in fetched]

    async def get_events(
        self,
        run_id: str,
        *,
        kind: str | None = None,
        after_seq: int | None = None,
        limit: int = 100,
    ) -> list[EventRow]:
        stmt = (
            sa.select(events)
            .where(events.c.run_id == run_id)
            .order_by(events.c.seq)
            .limit(limit)
        )
        if kind is not None:
            stmt = stmt.where(events.c.kind == kind)
        if after_seq is not None:
            stmt = stmt.where(events.c.seq > after_seq)
        async with self._engine.connect() as conn:
            result = await conn.execute(stmt)
            fetched = result.mappings().all()
        return [_event_row_from_mapping(row) for row in fetched]

    async def get_project_events(
        self,
        project_id: str,
        *,
        after_event_id: str | None = None,
        limit: int = 100,
    ) -> list[EventRow]:
        stmt = (
            sa.select(events)
            .select_from(events.join(runs, events.c.run_id == runs.c.run_id))
            .where(runs.c.project_id == project_id)
            .order_by(events.c.event_id)
            .limit(limit)
        )
        if after_event_id is not None:
            stmt = stmt.where(events.c.event_id > after_event_id)
        async with self._engine.connect() as conn:
            result = await conn.execute(stmt)
            fetched = result.mappings().all()
        return [_event_row_from_mapping(row) for row in fetched]


def _run_row_from_mapping(row: sa.RowMapping) -> RunRow:
    return RunRow(
        run_id=row["run_id"],
        project_id=row["project_id"],
        framework=row["framework"],
        status=row["status"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        tags=row["tags"],
        totals=row["totals"],
    )


def _event_row_from_mapping(row: sa.RowMapping) -> EventRow:
    return EventRow(
        run_id=row["run_id"],
        seq=row["seq"],
        event_id=row["event_id"],
        kind=row["kind"],
        ts=row["ts"],
        step_id=row["step_id"],
        agent_id=row["agent_id"],
        fingerprint=row["fingerprint"],
        payload=row["payload"],
        blobs=row["blobs"],
    )
