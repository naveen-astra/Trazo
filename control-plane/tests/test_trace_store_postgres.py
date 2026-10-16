"""Integration tests for PostgresTraceStore against a live, migrated Postgres.

Skipped automatically when Postgres isn't reachable (DEVELOPMENT_GUIDE.md:
these need `make up`). test_trace_store_memory.py already proves the
upsert-idempotency DoD against the fake; this file proves the same
contract holds against real Postgres ON CONFLICT DO UPDATE semantics.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine

from trazo_server.config import Settings
from trazo_server.store.engine import create_engine
from trazo_server.store.postgres_trace_store import PostgresTraceStore
from trazo_server.store.rows import (
    AppendedEvent,
    DetectionRow,
    EventRow,
    PolicyDecisionRow,
    ReplayReportRow,
    RunRow,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_NOW = datetime(2026, 7, 18, 9, 30, tzinfo=timezone.utc)


def _alembic_config() -> Config:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "migrations"))
    return cfg


@pytest.fixture(scope="module", autouse=True)
def _skip_without_postgres() -> None:
    """conftest.py's session-scoped _ensure_schema already migrated (or
    tried to) before any test ran; this just preserves this file's own
    graceful skip for a Postgres-less local run — the session fixture
    fails open rather than skipping, since skipping there would skip
    every test in the run, not just this file's."""
    try:
        command.upgrade(_alembic_config(), "head")
    except Exception:
        pytest.skip("Postgres not reachable — run `make up` for integration coverage")


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_engine(Settings().database_url)
    yield eng
    await eng.dispose()


@pytest.fixture
def ids() -> tuple[str, str]:
    # unique per test so parallel/repeated runs don't collide on shared Postgres
    suffix = uuid.uuid4().hex[:8]
    return f"proj_{suffix}", f"run_{suffix}"


def _run_row(project_id: str, run_id: str, **overrides: object) -> RunRow:
    defaults: dict[str, object] = {
        "run_id": run_id,
        "project_id": project_id,
        "framework": "langgraph",
        "status": "running",
        "started_at": _NOW,
        "finished_at": None,
        "tags": {},
        "totals": {},
    }
    defaults.update(overrides)
    return RunRow(**defaults)  # type: ignore[arg-type]


async def test_postgres_store__upsert_run_then_get_round_trips(
    engine: AsyncEngine, ids: tuple[str, str]
) -> None:
    project_id, run_id = ids
    store = PostgresTraceStore(engine)
    await store.ensure_project(project_id, f"test-{project_id}")

    await store.upsert_run(_run_row(project_id, run_id))
    fetched = await store.get_run(run_id)

    assert fetched is not None
    assert fetched.status == "running"


async def test_postgres_store__upsert_run_twice_updates_rollup_in_place(
    engine: AsyncEngine, ids: tuple[str, str]
) -> None:
    project_id, run_id = ids
    store = PostgresTraceStore(engine)
    await store.ensure_project(project_id, f"test-{project_id}")
    await store.upsert_run(_run_row(project_id, run_id, status="running"))

    await store.upsert_run(
        _run_row(
            project_id,
            run_id,
            status="ok",
            finished_at=_NOW,
            totals={"events": 9, "llm_calls": 1},
        )
    )

    fetched = await store.get_run(run_id)
    assert fetched is not None
    assert fetched.status == "ok"
    assert fetched.totals == {"events": 9, "llm_calls": 1}


async def test_postgres_store__upsert_run_authoritative_reclaims_creation_fields(
    engine: AsyncEngine, ids: tuple[str, str]
) -> None:
    """A placeholder row can legitimately be created before ``run.started``
    lands -- the synchronous policy endpoint does exactly that so its
    ``policy.decision`` event has a run to hang off (events.run_id is a FK).
    Without `authoritative`, that placeholder's stand-in framework and
    timestamp would be permanent, because run.started would then only ever
    be a conflicting update, and ON CONFLICT DO UPDATE deliberately does not
    touch the creation fields.
    """
    project_id, run_id = ids
    store = PostgresTraceStore(engine)
    await store.ensure_project(project_id, f"test-{project_id}")
    placeholder_started = datetime(2026, 7, 18, 8, 0, tzinfo=timezone.utc)
    await store.upsert_run(
        _run_row(
            project_id,
            run_id,
            framework="unknown",
            started_at=placeholder_started,
            tags={},
        )
    )

    await store.upsert_run(
        _run_row(
            project_id,
            run_id,
            framework="langgraph",
            started_at=_NOW,
            tags={"injected_failure": {"class": "budget"}},
        ),
        authoritative=True,
    )

    fetched = await store.get_run(run_id)
    assert fetched is not None
    assert fetched.framework == "langgraph"
    assert fetched.started_at == _NOW
    assert fetched.tags == {"injected_failure": {"class": "budget"}}


async def test_postgres_store__server_event_for_an_unseen_run_creates_it(
    engine: AsyncEngine, ids: tuple[str, str]
) -> None:
    """`events.run_id` is a foreign key, and a policy decision or detection
    can be recorded before the run's own `run.started` reaches the store.
    The write must create a placeholder run, not fail."""
    _, run_id = ids
    store = PostgresTraceStore(engine)

    appended = await store.append_server_event(
        run_id=run_id,
        project=f"test-{run_id}",
        after_seq=None,
        event_id=f"evt_{run_id}",
        kind="policy.decision",
        ts=_NOW,
        payload={"decision": "deny", "policy_id": "cost_cap"},
    )

    assert (appended.seq, appended.sub_seq) == (0, 1)
    run = await store.get_run(run_id)
    assert run is not None
    assert run.framework == "unknown"


async def test_postgres_store__upsert_events_idempotent_on_run_id_and_seq(
    engine: AsyncEngine, ids: tuple[str, str]
) -> None:
    project_id, run_id = ids
    store = PostgresTraceStore(engine)
    await store.ensure_project(project_id, f"test-{project_id}")
    await store.upsert_run(_run_row(project_id, run_id))
    batch = [
        EventRow(
            run_id=run_id,
            seq=0,
            event_id="evt_0",
            kind="run.started",
            ts=_NOW,
            step_id=None,
            agent_id=None,
            fingerprint=None,
            payload={"framework": "langgraph"},
            blobs=[],
        ),
        EventRow(
            run_id=run_id,
            seq=1,
            event_id="evt_1",
            kind="llm.call",
            ts=_NOW,
            step_id=None,
            agent_id=None,
            fingerprint="sha256:" + "a" * 64,
            payload={"model": "gpt-4o-mini"},
            blobs=[],
        ),
    ]

    await store.upsert_events(batch)
    await store.upsert_events(batch)  # re-send: simulates an ingest retry

    events = await store.get_events(run_id)
    assert [e.seq for e in events] == [0, 1]


async def test_postgres_store__upsert_events_overwrites_same_seq(
    engine: AsyncEngine, ids: tuple[str, str]
) -> None:
    project_id, run_id = ids
    store = PostgresTraceStore(engine)
    await store.ensure_project(project_id, f"test-{project_id}")
    await store.upsert_run(_run_row(project_id, run_id))
    base_event = EventRow(
        run_id=run_id,
        seq=0,
        event_id="evt_0",
        kind="run.started",
        ts=_NOW,
        step_id=None,
        agent_id=None,
        fingerprint=None,
        payload={"framework": "langgraph"},
        blobs=[],
    )
    await store.upsert_events([base_event])

    updated_event = EventRow(
        run_id=run_id,
        seq=0,
        event_id="evt_0",
        kind="run.started",
        ts=_NOW,
        step_id=None,
        agent_id="fixed-agent",
        fingerprint=None,
        payload={"framework": "langgraph"},
        blobs=[],
    )
    await store.upsert_events([updated_event])

    [event] = await store.get_events(run_id)
    assert event.agent_id == "fixed-agent"


def _sdk_row(run_id: str, seq: int, *, kind: str = "step.started") -> EventRow:
    return EventRow(
        run_id=run_id,
        seq=seq,
        event_id=f"evt_{run_id}_{seq:05d}",
        kind=kind,
        ts=_NOW,
        step_id=None,
        agent_id=None,
        fingerprint=None,
        payload={"name": f"step-{seq}"},
        blobs=[],
    )


async def _append_detection(
    store: PostgresTraceStore,
    run_id: str,
    *,
    after_seq: int | None,
    event_id: str,
    idempotency_key: str | None = None,
) -> AppendedEvent:
    return await store.append_server_event(
        run_id=run_id,
        project=f"test-{run_id}",
        after_seq=after_seq,
        event_id=event_id,
        kind="detection.raised",
        ts=_NOW,
        payload={"detector": "loop"},
        idempotency_key=idempotency_key,
    )


async def test_postgres_store__server_events_order_right_after_their_sdk_event(
    engine: AsyncEngine, ids: tuple[str, str]
) -> None:
    project_id, run_id = ids
    store = PostgresTraceStore(engine)
    await store.ensure_project(project_id, f"test-{project_id}")
    await store.upsert_run(_run_row(project_id, run_id))
    await store.upsert_events([_sdk_row(run_id, seq) for seq in range(3)])

    first = await _append_detection(store, run_id, after_seq=1, event_id=f"a_{run_id}")
    second = await _append_detection(store, run_id, after_seq=1, event_id=f"b_{run_id}")

    assert (first.seq, first.sub_seq, second.sub_seq) == (1, 1, 2)
    order = [(e.seq, e.sub_seq) for e in await store.get_events(run_id)]
    assert order == [(0, 0), (1, 0), (1, 1), (1, 2), (2, 0)]


async def test_postgres_store__concurrent_server_events_take_distinct_slots(
    engine: AsyncEngine, ids: tuple[str, str]
) -> None:
    project_id, run_id = ids
    store = PostgresTraceStore(engine)
    await store.ensure_project(project_id, f"test-{project_id}")
    await store.upsert_run(_run_row(project_id, run_id))
    await store.upsert_events([_sdk_row(run_id, 0, kind="run.started")])

    appended = await asyncio.gather(
        *(
            _append_detection(store, run_id, after_seq=0, event_id=f"evt_{run_id}_{i}")
            for i in range(10)
        )
    )

    assert sorted(a.sub_seq for a in appended) == list(range(1, 11))


async def test_postgres_store__concurrent_retries_of_one_detection_record_it_once(
    engine: AsyncEngine, ids: tuple[str, str]
) -> None:
    project_id, run_id = ids
    store = PostgresTraceStore(engine)
    await store.ensure_project(project_id, f"test-{project_id}")
    await store.upsert_run(_run_row(project_id, run_id))

    appended = await asyncio.gather(
        *(
            _append_detection(
                store, run_id, after_seq=0, event_id=f"evt_{i}", idempotency_key="k"
            )
            for i in range(5)
        )
    )

    assert sum(a.created for a in appended) == 1
    assert len({a.event_id for a in appended}) == 1
    assert len(await store.get_server_events(run_id)) == 1


async def test_postgres_store__sdk_batches_and_server_events_interleave_safely(
    engine: AsyncEngine, ids: tuple[str, str]
) -> None:
    """The workload that deadlocked live on 2026-10-16 -- the store worker
    upserting a run's SDK events while the detector records detections on
    the same run -- and, behind it, the silent overwrite: each server event
    used to take `max + 1`, a number the SDK had already used for an event
    still in flight. Run it many times concurrently: nothing may raise, and
    every event of both kinds must survive."""
    project_id, run_id = ids
    store = PostgresTraceStore(engine)
    await store.ensure_project(project_id, f"test-{project_id}")
    await store.upsert_run(_run_row(project_id, run_id))

    rounds, batch = 30, 8
    detections: list[str] = []

    async def sdk_batch(r: int) -> None:
        await store.upsert_events(
            [_sdk_row(run_id, r * batch + i) for i in range(batch)]
        )

    async def detection(r: int) -> None:
        event_id = f"evt_det_{run_id}_{r}"
        detections.append(event_id)
        # Reacting to an event early in the current batch, while the rest
        # of the batch (higher seqs) is still being written.
        await _append_detection(
            store,
            run_id,
            after_seq=r * batch,
            event_id=event_id,
            idempotency_key=f"detection:{r}",
        )

    for r in range(rounds):
        await asyncio.gather(sdk_batch(r), detection(r), detection(r))

    stored = await store.get_events(run_id, limit=10_000)
    sdk_ids = {e.event_id for e in stored if e.sub_seq == 0}
    server_ids = {e.event_id for e in stored if e.sub_seq > 0}
    assert len(sdk_ids) == rounds * batch, "an SDK event was lost or overwritten"
    assert len(server_ids) == rounds, "a detection was lost or duplicated"
    assert server_ids <= set(detections)


async def test_postgres_store__insert_detection_then_list_round_trips(
    engine: AsyncEngine, ids: tuple[str, str]
) -> None:
    project_id, run_id = ids
    store = PostgresTraceStore(engine)
    await store.ensure_project(project_id, f"test-{project_id}")
    await store.upsert_run(_run_row(project_id, run_id))
    detection = DetectionRow(
        detection_id=f"det_{run_id}",
        run_id=run_id,
        detector="loop",
        severity="warn",
        raised_at=_NOW,
        evidence=[{"run_id": run_id, "seq": 5}],
        details={"repeat_count": 4},
    )

    await store.insert_detection(detection)

    [fetched] = await store.list_detections(run_id)
    assert fetched == detection


async def test_postgres_store__insert_detection_is_idempotent_on_detection_id(
    engine: AsyncEngine, ids: tuple[str, str]
) -> None:
    project_id, run_id = ids
    store = PostgresTraceStore(engine)
    await store.ensure_project(project_id, f"test-{project_id}")
    await store.upsert_run(_run_row(project_id, run_id))
    detection = DetectionRow(
        detection_id=f"det_{run_id}",
        run_id=run_id,
        detector="loop",
        severity="warn",
        raised_at=_NOW,
        evidence=[],
        details={},
    )

    await store.insert_detection(detection)
    await store.insert_detection(detection)  # simulates a bus redelivery

    assert len(await store.list_detections(run_id)) == 1


async def test_postgres_store__insert_policy_decision_then_list_round_trips(
    engine: AsyncEngine, ids: tuple[str, str]
) -> None:
    project_id, run_id = ids
    store = PostgresTraceStore(engine)
    await store.ensure_project(project_id, f"test-{project_id}")
    await store.upsert_run(_run_row(project_id, run_id))
    decision = PolicyDecisionRow(
        decision_id=f"dec_{run_id}",
        run_id=run_id,
        policy_id="cost_cap",
        action_kind="tool.call",
        action_fp=f"sha256:{'a' * 64}",
        decision="deny",
        mode="enforce",
        reasons=["over cap"],
        decided_at=_NOW,
        eval_ms=12.5,
    )

    await store.insert_policy_decision(decision)

    [fetched] = await store.list_policy_decisions(run_id)
    assert fetched.decision_id == decision.decision_id
    assert fetched.policy_id == "cost_cap"
    assert fetched.decision == "deny"
    assert fetched.reasons == ["over cap"]
    assert (
        fetched.eval_ms == 12
    )  # rounded to the integer column, see insert_policy_decision


async def test_postgres_store__insert_policy_decision_is_idempotent_on_decision_id(
    engine: AsyncEngine, ids: tuple[str, str]
) -> None:
    project_id, run_id = ids
    store = PostgresTraceStore(engine)
    await store.ensure_project(project_id, f"test-{project_id}")
    await store.upsert_run(_run_row(project_id, run_id))
    decision = PolicyDecisionRow(
        decision_id=f"dec_{run_id}",
        run_id=run_id,
        policy_id="cost_cap",
        action_kind="tool.call",
        action_fp=f"sha256:{'a' * 64}",
        decision="deny",
        mode="enforce",
        reasons=[],
        decided_at=_NOW,
        eval_ms=1.0,
    )

    await store.insert_policy_decision(decision)
    await store.insert_policy_decision(decision)  # simulates a bus redelivery

    assert len(await store.list_policy_decisions(run_id)) == 1


async def test_postgres_store__get_replay_report_is_none_before_any_verify(
    engine: AsyncEngine, ids: tuple[str, str]
) -> None:
    _project_id, run_id = ids
    store = PostgresTraceStore(engine)

    assert await store.get_replay_report(run_id) is None


async def test_postgres_store__upsert_replay_report_then_get_round_trips(
    engine: AsyncEngine, ids: tuple[str, str]
) -> None:
    project_id, run_id = ids
    store = PostgresTraceStore(engine)
    await store.ensure_project(project_id, f"test-{project_id}")
    await store.upsert_run(_run_row(project_id, run_id))
    report = ReplayReportRow(
        run_id=run_id,
        boundary_fidelity=1.0,
        state_fidelity=1.0,
        matched=2,
        reordered=0,
        divergences=[],
        replay_overhead=0.42,
        verified_at=_NOW,
    )

    await store.upsert_replay_report(report)
    fetched = await store.get_replay_report(run_id)

    assert fetched is not None
    assert fetched.boundary_fidelity == 1.0
    assert fetched.state_fidelity == 1.0
    assert fetched.matched == 2
    assert fetched.replay_overhead == 0.42
    assert fetched.divergences == []


async def test_postgres_store__upsert_replay_report_replaces_not_accumulates(
    engine: AsyncEngine, ids: tuple[str, str]
) -> None:
    """A re-verify overwrites the previous report — only the latest
    result against the current code is meaningful (ReplayReportRow's
    docstring), so this must never grow a history."""
    project_id, run_id = ids
    store = PostgresTraceStore(engine)
    await store.ensure_project(project_id, f"test-{project_id}")
    await store.upsert_run(_run_row(project_id, run_id))
    await store.upsert_replay_report(
        ReplayReportRow(
            run_id=run_id,
            boundary_fidelity=0.5,
            state_fidelity=0.5,
            matched=1,
            reordered=0,
            divergences=[{"kind": "tool.call", "reason": "fingerprint mismatch"}],
            replay_overhead=None,
            verified_at=_NOW,
        )
    )

    await store.upsert_replay_report(
        ReplayReportRow(
            run_id=run_id,
            boundary_fidelity=1.0,
            state_fidelity=1.0,
            matched=2,
            reordered=0,
            divergences=[],
            replay_overhead=0.3,
            verified_at=_NOW,
        )
    )

    fetched = await store.get_replay_report(run_id)
    assert fetched is not None
    assert fetched.boundary_fidelity == 1.0
    assert fetched.divergences == []
