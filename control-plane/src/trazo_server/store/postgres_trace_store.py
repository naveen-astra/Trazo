"""PostgresTraceStore: the MVP TraceStore implementation (ADR-003)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from trazo_server.store.models import (
    detections,
    events,
    policy_decisions,
    projects,
    runs,
)
from trazo_server.store.rows import DetectionRow, EventRow, PolicyDecisionRow, RunRow


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
        project_id: str | None,
        *,
        after_event_id: str | None = None,
        limit: int = 100,
    ) -> list[EventRow]:
        stmt = (
            sa.select(events)
            .select_from(events.join(runs, events.c.run_id == runs.c.run_id))
            .order_by(events.c.event_id)
            .limit(limit)
        )
        if project_id is not None:
            stmt = stmt.where(runs.c.project_id == project_id)
        if after_event_id is not None:
            stmt = stmt.where(events.c.event_id > after_event_id)
        async with self._engine.connect() as conn:
            result = await conn.execute(stmt)
            fetched = result.mappings().all()
        return [_event_row_from_mapping(row) for row in fetched]

    async def latest_event_id(self, project_id: str | None) -> str | None:
        # ORDER BY event_id DESC LIMIT 1 rather than max(): with a project
        # filter the join makes an index-backed backwards scan the cheaper
        # plan, and without one it degrades to the same thing max() does.
        stmt = (
            sa.select(events.c.event_id)
            .select_from(events.join(runs, events.c.run_id == runs.c.run_id))
            .order_by(events.c.event_id.desc())
            .limit(1)
        )
        if project_id is not None:
            stmt = stmt.where(runs.c.project_id == project_id)
        async with self._engine.connect() as conn:
            result = await conn.execute(stmt)
            return result.scalar_one_or_none()

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
        async with self._engine.begin() as conn:
            # Lock the run's own `runs` row (present for every run before
            # its first event, unlike an events row) rather than the last
            # events row: locking `ORDER BY seq DESC LIMIT 1 ... FOR
            # UPDATE` looked equivalent but isn't — when a blocked
            # transaction's FOR UPDATE wait resolves, Postgres re-checks
            # only the *same physical row* it originally matched
            # (EvalPlanQual), it does not re-run the ORDER BY/LIMIT scan.
            # Since a concurrent insert doesn't modify that row, the
            # unblocked transaction reads the same stale "last seq" the
            # first transaction started from, and both assign the same
            # next_seq -- reproduced by the concurrent-append test as a
            # duplicate-key error on `events_pkey`. Locking the `runs` row
            # instead makes every concurrent reservation for this run_id
            # wait for the whole transaction (lock plus insert plus
            # commit), so each one's subsequent MAX(seq) read is against
            # the latest committed state.
            await conn.execute(
                sa.select(runs.c.run_id)
                .where(runs.c.run_id == run_id)
                .with_for_update()
            )
            result = await conn.execute(
                sa.select(sa.func.max(events.c.seq)).where(events.c.run_id == run_id)
            )
            last_seq = result.scalar_one_or_none()
            next_seq = 0 if last_seq is None else last_seq + 1
            await conn.execute(
                events.insert().values(
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
            )
        return next_seq

    async def insert_detection(self, detection: DetectionRow) -> None:
        stmt = (
            pg_insert(detections)
            .values(
                detection_id=detection.detection_id,
                run_id=detection.run_id,
                detector=detection.detector,
                severity=detection.severity,
                raised_at=detection.raised_at,
                evidence=detection.evidence,
                details=detection.details,
            )
            .on_conflict_do_nothing(index_elements=[detections.c.detection_id])
        )
        async with self._engine.begin() as conn:
            await conn.execute(stmt)

    async def list_detections(self, run_id: str) -> list[DetectionRow]:
        stmt = (
            sa.select(detections)
            .where(detections.c.run_id == run_id)
            .order_by(detections.c.raised_at.desc())
        )
        async with self._engine.connect() as conn:
            result = await conn.execute(stmt)
            fetched = result.mappings().all()
        return [_detection_row_from_mapping(row) for row in fetched]

    async def insert_policy_decision(self, decision: PolicyDecisionRow) -> None:
        stmt = (
            pg_insert(policy_decisions)
            .values(
                decision_id=decision.decision_id,
                run_id=decision.run_id,
                policy_id=decision.policy_id,
                action_kind=decision.action_kind,
                action_fp=decision.action_fp,
                decision=decision.decision,
                mode=decision.mode,
                reasons=decision.reasons,
                decided_at=decision.decided_at,
                # policy_decisions.eval_ms is an integer column
                # (DATABASE.md §2) -- rounded here; PolicyDecisionRow
                # itself keeps the float the policy.decision event
                # payload actually carries (eval_latency_ms).
                eval_ms=round(decision.eval_ms),
            )
            .on_conflict_do_nothing(index_elements=[policy_decisions.c.decision_id])
        )
        async with self._engine.begin() as conn:
            await conn.execute(stmt)

    async def list_policy_decisions(self, run_id: str) -> list[PolicyDecisionRow]:
        stmt = (
            sa.select(policy_decisions)
            .where(policy_decisions.c.run_id == run_id)
            .order_by(policy_decisions.c.decided_at.desc())
        )
        async with self._engine.connect() as conn:
            result = await conn.execute(stmt)
            fetched = result.mappings().all()
        return [_policy_decision_row_from_mapping(row) for row in fetched]

    async def list_recent_detections(self, *, limit: int) -> list[DetectionRow]:
        stmt = (
            sa.select(detections).order_by(detections.c.raised_at.desc()).limit(limit)
        )
        async with self._engine.connect() as conn:
            result = await conn.execute(stmt)
            fetched = result.mappings().all()
        return [_detection_row_from_mapping(row) for row in fetched]

    async def list_recent_policy_decisions(
        self, *, limit: int
    ) -> list[PolicyDecisionRow]:
        stmt = (
            sa.select(policy_decisions)
            .order_by(policy_decisions.c.decided_at.desc())
            .limit(limit)
        )
        async with self._engine.connect() as conn:
            result = await conn.execute(stmt)
            fetched = result.mappings().all()
        return [_policy_decision_row_from_mapping(row) for row in fetched]

    async def list_recent_events(
        self, *, kind: str | None = None, limit: int
    ) -> list[EventRow]:
        # event_id breaks ts ties. Fast agents emit many events inside one
        # millisecond, and ts alone left the feed showing a run's events
        # shuffled (…54, 52, 53, 50, 51…). event_id is a ULID, monotonic
        # within a run, so it restores true emission order.
        stmt = (
            sa.select(events)
            .order_by(events.c.ts.desc(), events.c.event_id.desc())
            .limit(limit)
        )
        if kind is not None:
            # events_kind is (run_id, kind, seq); a cross-run kind filter
            # doesn't hit it, so this leans on the ts ordering + LIMIT.
            # Fine at the bounded sizes these feeds ask for; revisit with
            # a (kind, ts) index if a measured page load says to.
            stmt = stmt.where(events.c.kind == kind)
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


def _detection_row_from_mapping(row: sa.RowMapping) -> DetectionRow:
    return DetectionRow(
        detection_id=row["detection_id"],
        run_id=row["run_id"],
        detector=row["detector"],
        severity=row["severity"],
        raised_at=row["raised_at"],
        evidence=row["evidence"],
        details=row["details"],
    )


def _policy_decision_row_from_mapping(row: sa.RowMapping) -> PolicyDecisionRow:
    return PolicyDecisionRow(
        decision_id=row["decision_id"],
        run_id=row["run_id"],
        policy_id=row["policy_id"],
        action_kind=row["action_kind"],
        action_fp=row["action_fp"],
        decision=row["decision"],
        mode=row["mode"],
        reasons=row["reasons"],
        decided_at=row["decided_at"],
        eval_ms=float(row["eval_ms"]),
    )
