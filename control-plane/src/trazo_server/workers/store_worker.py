"""Store worker: bus consumer -> TraceStore persist (TRZ-P1-06).

Consumes ``EVENTS_STREAM`` under ``STORE_WORKER_GROUP``, persists each
event via TraceStore (idempotent on (run_id, seq) — reprocessing the same
message after a crash-and-reclaim is always safe, never duplicates),
offloads any offloadable payload field over the 32KB inline limit to
BlobStore, maintains the run rollup on ``run.started``/``run.finished``,
and marks runs stale past the configured TTL. Poison messages (JSON/schema
validation failure) go to the DLQ via ``EventBus.dead_letter``, never
blocking the consumer group (ARCHITECTURE.md §7).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import structlog
from pydantic import ValidationError

from trazo_server.bus.protocol import BUS_BLOCK_MS, BusMessage, EventBus
from trazo_server.events import Event, EventAdapter
from trazo_server.metrics import BUS_DLQ_DEPTH_MESSAGES, BUS_LAG_MESSAGES
from trazo_server.project_id import derive_project_id
from trazo_server.store.blob_store import BlobStore
from trazo_server.store.rows import DetectionRow, EventRow, PolicyDecisionRow, RunRow
from trazo_server.store.trace_store import TraceStore
from trazo_server.topics import EVENTS_STREAM, STORE_WORKER_GROUP

log = structlog.get_logger(__name__)

_BLOB_INLINE_MAX = 32_768  # bytes; ARCHITECTURE.md §6 TRAZO_BLOB_INLINE_MAX

# Which payload fields may be offloaded, per event kind (EVENTS.md §2).
_OFFLOADABLE_FIELDS_BY_KIND: dict[str, frozenset[str]] = {
    "run.started": frozenset({"entry_input"}),
    "step.started": frozenset({"state_before"}),
    "step.finished": frozenset({"state_after"}),
    "llm.call": frozenset({"messages_in", "response"}),
    "tool.call": frozenset({"args", "result"}),
    "memory.read": frozenset({"query", "results"}),
    "memory.write": frozenset({"value"}),
    "agent.message": frozenset({"content"}),
    "plan.updated": frozenset({"plan"}),
    "human.checkpoint": frozenset({"response"}),
}


def _detection_id_from_event(event_id: str) -> str:
    """Derive a stable detection_id from the event_id that carries it —
    idempotent under bus redelivery (the same detection.raised event
    always yields the same detection_id, so insert_detection's
    on-conflict-do-nothing correctly no-ops on a repeat) without needing
    the detections projection to invent its own identity scheme."""
    _, _, ulid = event_id.partition("_")
    return f"det_{ulid}"


def _policy_decision_id_from_event(event_id: str) -> str:
    """Same derivation as ``_detection_id_from_event``, for
    policy_decisions' own identity (TRZ-P6-05)."""
    _, _, ulid = event_id.partition("_")
    return f"dec_{ulid}"


class StoreWorker:
    """Drains EVENTS_STREAM into TraceStore/BlobStore; see module docstring."""

    def __init__(
        self,
        *,
        bus: EventBus,
        trace_store: TraceStore,
        blob_store: BlobStore,
        consumer_name: str,
        stale_run_ttl: timedelta = timedelta(hours=6),
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._bus = bus
        self._trace_store = trace_store
        self._blob_store = blob_store
        self._consumer_name = consumer_name
        self._stale_run_ttl = stale_run_ttl
        self._clock = clock

    async def ensure_group(self) -> None:
        await self._bus.ensure_group(EVENTS_STREAM, STORE_WORKER_GROUP)

    async def poll_once(self, *, count: int = 100, block_ms: int = BUS_BLOCK_MS) -> int:
        """Read and process one batch of new messages; returns count read."""
        messages = await self._bus.read_group(
            EVENTS_STREAM,
            STORE_WORKER_GROUP,
            self._consumer_name,
            count=count,
            block_ms=block_ms,
        )
        await self._process_batch(messages)
        return len(messages)

    async def reclaim_once(self, *, min_idle_ms: int, count: int = 100) -> int:
        """Recover messages abandoned by a crashed consumer (XAUTOCLAIM);
        returns count reclaimed and processed."""
        messages = await self._bus.reclaim_stale(
            EVENTS_STREAM,
            STORE_WORKER_GROUP,
            self._consumer_name,
            min_idle_ms=min_idle_ms,
            count=count,
        )
        await self._process_batch(messages)
        return len(messages)

    async def scan_stale_runs(self) -> int:
        """Mark 'running' runs whose started_at is past the TTL as 'stale';
        returns count marked."""
        now = self._clock()
        cutoff = now - self._stale_run_ttl
        running = await self._trace_store.list_runs(status="running", limit=1000)
        marked = 0
        for run in running:
            if run.started_at < cutoff:
                await self._trace_store.upsert_run(
                    replace(run, status="stale", finished_at=now)
                )
                marked += 1
        return marked

    async def run_forever(
        self,
        *,
        poll_block_ms: int = BUS_BLOCK_MS,
        reclaim_min_idle_ms: int = 30_000,
        reclaim_every: int = 10,
        stale_scan_every: int = 60,
    ) -> None:
        """Run the consume-persist loop until cancelled.

        Never raises on a transient bus/store error — logs and keeps going,
        because a worker that crashes the whole control-plane process on a
        momentary Redis/Postgres hiccup is worse than one that's briefly
        behind (ARCHITECTURE.md §7: workers never block the group).
        Cancellation (task shutdown) propagates normally.
        """
        iterations = 0
        group_ready = False
        while True:
            try:
                if not group_ready:
                    # Inside the loop, not a call before it: this is the
                    # same "must not crash the process on a Redis/Postgres
                    # hiccup" contract the rest of the loop already has —
                    # a bus that's unreachable when the worker *starts*
                    # (e.g. Redis still coming up) is transient, not fatal,
                    # and ensure_group() is documented idempotent so
                    # retrying it costs nothing once the bus is back.
                    await self.ensure_group()
                    group_ready = True
                iterations += 1
                # The poll gets its own handler so a failing read cannot
                # skip the reclaim below. That is precisely the case
                # reclaim exists for: a read that times out *after* Redis
                # has already moved the batch into the group's pending
                # list strands those messages, and only XAUTOCLAIM gets
                # them back. Gating recovery behind a successful poll made
                # the failure self-sustaining — observed live as a worker
                # wedged with 167 pending messages, persisting nothing and
                # never reclaiming any of them.
                poll_failed = False
                try:
                    await self.poll_once(block_ms=poll_block_ms)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("store_worker.poll_failed")
                    self._reraise_if_cancelling()
                    poll_failed = True
                if iterations % reclaim_every == 0:
                    await self.reclaim_once(min_idle_ms=reclaim_min_idle_ms)
                if iterations % stale_scan_every == 0:
                    await self.scan_stale_runs()
                await self._refresh_bus_metrics()
                if poll_failed:
                    # Back off exactly as the outer handler does. Without
                    # this the loop would hot-spin on a bus that is failing
                    # fast, which is the other way to make a worker useless.
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("store_worker.iteration_failed")
                self._reraise_if_cancelling()
                await asyncio.sleep(1)

    @staticmethod
    def _reraise_if_cancelling() -> None:
        """Turn a masked cancellation back into CancelledError.

        redis-py's own internal async_timeout converts a real cancellation
        delivered mid-poll (this task's own .cancel(), e.g. app shutdown)
        into a plain redis.exceptions.TimeoutError, indistinguishable by
        type from a genuine idle-poll timeout. Left unchecked, the broad
        excepts above would swallow it and retry forever, hanging whatever
        awaits this task. Task.cancelling() (3.11+) tells them apart.
        """
        task = asyncio.current_task()
        if task is not None and task.cancelling() > 0:
            raise asyncio.CancelledError() from None

    async def _refresh_bus_metrics(self) -> None:
        """Update the P1-08 bus-lag/DLQ-depth gauges from current bus state."""
        BUS_LAG_MESSAGES.set(await self._bus.lag(EVENTS_STREAM, STORE_WORKER_GROUP))
        BUS_DLQ_DEPTH_MESSAGES.set(await self._bus.dlq_depth(EVENTS_STREAM))

    async def _process_batch(self, messages: list[BusMessage]) -> None:
        if not messages:
            return
        rows: list[EventRow] = []
        for message in messages:
            event = self._parse(message)
            if event is None:
                await self._bus.dead_letter(
                    EVENTS_STREAM,
                    STORE_WORKER_GROUP,
                    message,
                    reason="schema validation failed",
                )
                continue
            rows.append(await self._offload_and_build_row(event))
            await self._apply_rollup(event)

        if rows:
            await self._trace_store.upsert_events(rows)

        for message in messages:
            await self._bus.ack(EVENTS_STREAM, STORE_WORKER_GROUP, message.message_id)

    def _parse(self, message: BusMessage) -> Event | None:
        raw = message.fields.get("event")
        if raw is None:
            log.warning(
                "store_worker.missing_event_field", message_id=message.message_id
            )
            return None
        try:
            return EventAdapter.validate_json(raw)
        except ValidationError:
            log.warning("store_worker.invalid_event", message_id=message.message_id)
            return None

    async def _offload_and_build_row(self, event: Event) -> EventRow:
        payload = event.payload.model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
        offloadable = _OFFLOADABLE_FIELDS_BY_KIND.get(event.kind, frozenset())
        blob_entries: list[dict[str, object]] = []
        for field in offloadable:
            if field not in payload:
                continue
            encoded = json.dumps(payload[field], separators=(",", ":")).encode("utf-8")
            if len(encoded) <= _BLOB_INLINE_MAX:
                continue
            ref = await self._blob_store.put(encoded, content_type="application/json")
            payload[field] = {"$blob": ref.sha256}
            blob_entries.append(
                {"field": f"payload.{field}", "sha256": ref.sha256, "bytes": ref.bytes}
            )

        return EventRow(
            run_id=event.run_id,
            seq=event.seq,
            event_id=event.event_id,
            kind=event.kind,
            ts=event.ts,
            step_id=event.step_id,
            agent_id=event.agent_id,
            fingerprint=event.fingerprint,
            payload=payload,
            blobs=blob_entries,
        )

    async def _apply_rollup(self, event: Event) -> None:
        if event.kind == "run.started":
            project_id = derive_project_id(event.project)
            await self._trace_store.ensure_project(project_id, event.project)
            await self._trace_store.upsert_run(
                RunRow(
                    run_id=event.run_id,
                    project_id=project_id,
                    framework=event.payload.framework,
                    status="running",
                    started_at=event.ts,
                    finished_at=None,
                    tags=event.payload.tags,
                    totals={},
                ),
                # This event *is* the run's creation record, so it owns the
                # creation fields even when something else had to create the
                # row first (a policy.decision for a run still in flight, or
                # an out-of-order run.finished).
                authoritative=True,
            )
        elif event.kind == "run.finished":
            # project_id/framework/started_at/tags below are placeholders:
            # upsert_run only applies status/finished_at/totals on a
            # conflict (the normal case, since run.started already exists).
            # They matter only if run.finished is somehow the first event
            # TraceStore sees for this run_id (out-of-order delivery).
            project_id = derive_project_id(event.project)
            await self._trace_store.ensure_project(project_id, event.project)
            await self._trace_store.upsert_run(
                RunRow(
                    run_id=event.run_id,
                    project_id=project_id,
                    framework="unknown",
                    status=event.payload.status,
                    started_at=event.ts,
                    finished_at=event.ts,
                    tags={},
                    totals=event.payload.totals.model_dump(mode="json"),
                )
            )
        elif event.kind == "detection.raised":
            await self._trace_store.insert_detection(
                DetectionRow(
                    detection_id=_detection_id_from_event(event.event_id),
                    run_id=event.run_id,
                    detector=event.payload.detector,
                    severity=event.payload.severity,
                    raised_at=event.ts,
                    evidence=[
                        {"event_id": eid} for eid in event.payload.evidence_event_ids
                    ],
                    details=event.payload.details,
                )
            )
        elif event.kind == "policy.decision":
            await self._trace_store.insert_policy_decision(
                PolicyDecisionRow(
                    decision_id=_policy_decision_id_from_event(event.event_id),
                    run_id=event.run_id,
                    policy_id=event.payload.policy_id,
                    action_kind=event.payload.action_ref.kind,
                    action_fp=event.payload.action_ref.fingerprint,
                    decision=event.payload.decision,
                    mode=event.payload.mode,
                    reasons=event.payload.reasons,
                    decided_at=event.ts,
                    eval_ms=event.payload.eval_latency_ms,
                )
            )
