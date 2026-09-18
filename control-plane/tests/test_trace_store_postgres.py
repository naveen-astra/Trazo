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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from trazo_server.config import Settings
from trazo_server.store.engine import create_engine
from trazo_server.store.postgres_trace_store import PostgresTraceStore
from trazo_server.store.rows import (
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


async def test_postgres_store__append_event_rejects_an_unknown_run(
    engine: AsyncEngine, ids: tuple[str, str]
) -> None:
    """``events.run_id`` is a foreign key, so an event for a run that has no
    row cannot be written -- this is the constraint that forces the
    synchronous policy endpoint to create a placeholder run before
    recording its decision (see test_api_policy_postgres.py). Pinned here
    because the in-memory store has no FK and so silently accepts it, which
    is exactly how the endpoint shipped without the placeholder write.
    """
    project_id, run_id = ids
    store = PostgresTraceStore(engine)
    await store.ensure_project(project_id, f"test-{project_id}")

    with pytest.raises(IntegrityError):
        await store.append_event(
            run_id=run_id,  # never upsert_run'd
            event_id=f"evt_{run_id}",
            kind="policy.decision",
            ts=_NOW,
            fingerprint=None,
            payload={"decision": "deny", "policy_id": "cost_cap"},
        )


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


async def test_postgres_store__append_event_assigns_sequential_seqs(
    engine: AsyncEngine, ids: tuple[str, str]
) -> None:
    project_id, run_id = ids
    store = PostgresTraceStore(engine)
    await store.ensure_project(project_id, f"test-{project_id}")
    await store.upsert_run(_run_row(project_id, run_id))
    await store.upsert_events(
        [
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
            )
        ]
    )

    first = await store.append_event(
        run_id=run_id,
        event_id="evt_detection_1",
        kind="detection.raised",
        ts=_NOW,
        fingerprint=None,
        payload={"detector": "loop"},
    )
    second = await store.append_event(
        run_id=run_id,
        event_id="evt_detection_2",
        kind="detection.raised",
        ts=_NOW,
        fingerprint=None,
        payload={"detector": "budget"},
    )

    assert (first, second) == (1, 2)
    events = await store.get_events(run_id, after_seq=0)
    assert [e.seq for e in events] == [1, 2]


async def test_postgres_store__append_event_concurrent_calls_never_collide(
    engine: AsyncEngine, ids: tuple[str, str]
) -> None:
    """The whole point of locking the last-seq row inside the same
    transaction as the insert: N concurrent reservations for one run_id
    must still come out as N distinct, gapless seqs -- never a duplicate
    (which upsert_events would silently merge, masking a lost detection)."""
    project_id, run_id = ids
    store = PostgresTraceStore(engine)
    await store.ensure_project(project_id, f"test-{project_id}")
    await store.upsert_run(_run_row(project_id, run_id))
    await store.upsert_events(
        [
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
            )
        ]
    )

    async def _append(i: int) -> int:
        return await store.append_event(
            run_id=run_id,
            event_id=f"evt_concurrent_{i}",
            kind="detection.raised",
            ts=_NOW,
            fingerprint=None,
            payload={},
        )

    assigned = await asyncio.gather(*(_append(i) for i in range(10)))

    assert sorted(assigned) == list(range(1, 11))


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
