"""Unit tests for StoreWorker (TRZ-P1-06).

Uses InMemoryEventBus + InMemoryTraceStore + a tmp_path FilesystemBlobStore
so these run fully offline. The headline test
(``test_store_worker__kill_and_restart_mid_stream_loses_nothing``) proves
the task's DoD: a worker that crashes after persisting but before acking
does not lose events, and the reclaim-and-reprocess path does not
duplicate them (upsert_events is idempotent on (run_id, seq)).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

import pytest

from trazo_server.bus.memory import InMemoryEventBus
from trazo_server.bus.protocol import BusMessage, EventBus
from trazo_server.store.blob_fs import FilesystemBlobStore
from trazo_server.store.memory_trace_store import InMemoryTraceStore
from trazo_server.topics import EVENTS_STREAM
from trazo_server.workers.store_worker import StoreWorker

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE_RUN_PATH = _REPO_ROOT / "schema" / "examples" / "sample_run.ndjson"
_RUN_ID = "run_01J9Z8QK3V7XG2N4P5R6S7T8VW"


def _sample_lines() -> list[str]:
    return [line for line in _SAMPLE_RUN_PATH.read_text().splitlines() if line.strip()]


def _event(**overrides: object) -> dict:
    event: dict = {
        "schema": "trazo.v1",
        "event_id": "evt_01J9Z8QK3V0000000000000099",
        "run_id": "run_synthetic",
        "project": "synthetic-project",
        "seq": 0,
        "ts": "2026-07-18T09:30:00.000Z",
        "kind": "run.started",
        "payload": {
            "framework": "langgraph",
            "framework_version": "0.2.39",
            "sdk_version": "0.1.0",
            "entry_input": {"query": "hi"},
            "tags": {},
        },
    }
    event.update(overrides)
    return event


async def _publish(bus: EventBus, *events: dict) -> None:
    for event in events:
        await bus.publish(EVENTS_STREAM, {"event": json.dumps(event)})


def _make_worker(
    bus: EventBus,
    trace_store: InMemoryTraceStore,
    blob_store: FilesystemBlobStore,
    *,
    consumer_name: str = "worker-a",
    clock: object = None,
) -> StoreWorker:
    kwargs: dict = {
        "bus": bus,
        "trace_store": trace_store,
        "blob_store": blob_store,
        "consumer_name": consumer_name,
    }
    if clock is not None:
        kwargs["clock"] = clock
    return StoreWorker(**kwargs)


async def test_store_worker__persists_full_sample_run_and_builds_rollup(
    tmp_path: Path,
) -> None:
    bus = InMemoryEventBus()
    trace_store = InMemoryTraceStore()
    blob_store = FilesystemBlobStore(tmp_path)
    await _publish(bus, *(json.loads(line) for line in _sample_lines()))

    worker = _make_worker(bus, trace_store, blob_store)
    await worker.ensure_group()
    processed = await worker.poll_once(count=20, block_ms=0)

    assert processed == 9
    events = await trace_store.get_events(_RUN_ID)
    assert [e.seq for e in events] == list(range(9))

    run = await trace_store.get_run(_RUN_ID)
    assert run is not None
    assert run.framework == "langgraph"
    assert run.status == "ok"
    assert run.tags == {"env": "demo"}
    assert run.totals["llm_calls"] == 1


async def test_store_worker__projects_detection_raised_into_detections_table(
    tmp_path: Path,
) -> None:
    """TRZ-P5-06: a detection.raised event flowing through the same
    generic EVENTS_STREAM consumption every other kind uses must also
    populate the detections query-optimized projection (DATABASE.md §2),
    mirroring how run.started/run.finished already maintain the runs
    rollup."""
    bus = InMemoryEventBus()
    trace_store = InMemoryTraceStore()
    blob_store = FilesystemBlobStore(tmp_path)
    await _publish(
        bus,
        _event(
            event_id="evt_run_started",
            run_id="run_x",
            project="proj_x",
            seq=0,
            kind="run.started",
        ),
        _event(
            event_id="evt_detection_1",
            run_id="run_x",
            project="proj_x",
            seq=1,
            kind="detection.raised",
            payload={
                "detector": "loop",
                "severity": "warn",
                "evidence_event_ids": ["evt_a", "evt_b"],
                "details": {"repeat_count": 4},
                "window": {"step_count": 10},
            },
        ),
    )

    worker = _make_worker(bus, trace_store, blob_store)
    await worker.ensure_group()
    await worker.poll_once(count=20, block_ms=0)

    [detection] = await trace_store.list_detections("run_x")
    assert detection.detection_id == "det_detection_1"
    assert detection.detector == "loop"
    assert detection.severity == "warn"
    assert detection.details == {"repeat_count": 4}
    assert detection.evidence == [{"event_id": "evt_a"}, {"event_id": "evt_b"}]


async def test_store_worker__offloads_oversized_field_to_blob_store(
    tmp_path: Path,
) -> None:
    bus = InMemoryEventBus()
    trace_store = InMemoryTraceStore()
    blob_store = FilesystemBlobStore(tmp_path)
    big_result = {"data": "x" * 40_000}  # well over the 32KB inline limit
    event = _event(
        run_id="run_offload",
        kind="tool.call",
        fingerprint="sha256:" + "a" * 64,
        payload={
            "tool_name": "web_search",
            "args": {"query": "q"},
            "result": big_result,
            "status": "ok",
            "latency_ms": 10,
            "side_effect_class": "external",
        },
    )
    await _publish(bus, event)

    worker = _make_worker(bus, trace_store, blob_store)
    await worker.ensure_group()
    await worker.poll_once(count=10, block_ms=0)

    [stored] = await trace_store.get_events("run_offload")
    assert stored.payload["result"]["$blob"].startswith("sha256:")
    assert stored.blobs == [
        {
            "field": "payload.result",
            "sha256": stored.payload["result"]["$blob"],
            "bytes": len(json.dumps(big_result, separators=(",", ":")).encode()),
        }
    ]
    fetched_blob = await blob_store.get(stored.payload["result"]["$blob"])
    assert json.loads(fetched_blob) == big_result


async def test_store_worker__poison_event_goes_to_dlq_not_the_store(
    tmp_path: Path,
) -> None:
    bus = InMemoryEventBus()
    trace_store = InMemoryTraceStore()
    blob_store = FilesystemBlobStore(tmp_path)
    await bus.publish(EVENTS_STREAM, {"event": "not valid json at all"})

    worker = _make_worker(bus, trace_store, blob_store)
    await worker.ensure_group()
    processed = await worker.poll_once(count=10, block_ms=0)

    assert processed == 1
    assert await bus.dlq_depth(EVENTS_STREAM) == 1
    # nothing pending left on the source stream/group for the poison message
    assert await worker.reclaim_once(min_idle_ms=0, count=10) == 0


async def test_store_worker__scan_stale_runs_marks_old_running_runs_only(
    tmp_path: Path,
) -> None:
    bus = InMemoryEventBus()
    trace_store = InMemoryTraceStore()
    blob_store = FilesystemBlobStore(tmp_path)
    now = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    await _publish(
        bus,
        _event(run_id="run_old", ts="2000-01-01T00:00:00.000Z"),
        _event(run_id="run_recent", ts="2026-07-20T11:59:00.000Z"),
    )

    worker = _make_worker(bus, trace_store, blob_store, clock=lambda: now)
    await worker.ensure_group()
    await worker.poll_once(count=10, block_ms=0)

    marked = await worker.scan_stale_runs()

    assert marked == 1
    old_run = await trace_store.get_run("run_old")
    recent_run = await trace_store.get_run("run_recent")
    assert old_run is not None and old_run.status == "stale"
    assert old_run.finished_at == now
    assert recent_run is not None and recent_run.status == "running"


class _AckFailsOnceBus:
    """Wraps a real EventBus but raises on the first ack() call — simulates
    a worker process that dies right after persisting but before acking."""

    def __init__(self, inner: EventBus) -> None:
        self._inner = inner
        self._ack_calls = 0

    async def publish(self, stream: str, fields: Mapping[str, str]) -> str:
        return await self._inner.publish(stream, fields)

    async def ensure_group(self, stream: str, group: str) -> None:
        await self._inner.ensure_group(stream, group)

    async def read_group(
        self, stream: str, group: str, consumer: str, *, count: int, block_ms: int
    ) -> list[BusMessage]:
        return await self._inner.read_group(
            stream, group, consumer, count=count, block_ms=block_ms
        )

    async def ack(self, stream: str, group: str, message_id: str) -> None:
        self._ack_calls += 1
        if self._ack_calls == 1:
            raise RuntimeError("simulated crash: died after persist, before ack")
        await self._inner.ack(stream, group, message_id)

    async def reclaim_stale(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        min_idle_ms: int,
        count: int,
    ) -> list[BusMessage]:
        return await self._inner.reclaim_stale(
            stream, group, consumer, min_idle_ms=min_idle_ms, count=count
        )

    async def dead_letter(
        self, stream: str, group: str, message: BusMessage, reason: str
    ) -> None:
        await self._inner.dead_letter(stream, group, message, reason)

    async def dlq_depth(self, stream: str) -> int:
        return await self._inner.dlq_depth(stream)


async def test_store_worker__kill_and_restart_mid_stream_loses_nothing(
    tmp_path: Path,
) -> None:
    real_bus = InMemoryEventBus()
    trace_store = InMemoryTraceStore()
    blob_store = FilesystemBlobStore(tmp_path)
    await _publish(real_bus, *(json.loads(line) for line in _sample_lines()[:3]))

    crashing_bus = _AckFailsOnceBus(real_bus)
    worker_a = _make_worker(
        crashing_bus, trace_store, blob_store, consumer_name="worker-a"
    )
    await worker_a.ensure_group()

    with pytest.raises(RuntimeError):
        await worker_a.poll_once(count=10, block_ms=0)

    # the crash happened *after* the DB write: events already landed.
    assert len(await trace_store.get_events(_RUN_ID)) == 3

    # worker-a is gone; worker-b reclaims what's still pending (nothing was
    # acked before the crash) and reprocesses it.
    worker_b = _make_worker(real_bus, trace_store, blob_store, consumer_name="worker-b")
    reclaimed = await worker_b.reclaim_once(min_idle_ms=0, count=10)

    assert reclaimed == 3
    events_after_recovery = await trace_store.get_events(_RUN_ID)
    assert [e.seq for e in events_after_recovery] == [0, 1, 2]  # no duplicates

    # fully acked now: a third worker finds nothing left to reclaim.
    worker_c = _make_worker(real_bus, trace_store, blob_store, consumer_name="worker-c")
    assert await worker_c.reclaim_once(min_idle_ms=0, count=10) == 0
