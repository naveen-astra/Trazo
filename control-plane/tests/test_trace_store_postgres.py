"""Integration tests for PostgresTraceStore against a live, migrated Postgres.

Skipped automatically when Postgres isn't reachable (DEVELOPMENT_GUIDE.md:
these need `make up`). test_trace_store_memory.py already proves the
upsert-idempotency DoD against the fake; this file proves the same
contract holds against real Postgres ON CONFLICT DO UPDATE semantics.
"""

from __future__ import annotations

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
from trazo_server.store.rows import EventRow, RunRow

_REPO_ROOT = Path(__file__).resolve().parents[1]
_NOW = datetime(2026, 7, 18, 9, 30, tzinfo=timezone.utc)


def _alembic_config() -> Config:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "migrations"))
    return cfg


@pytest.fixture(scope="module", autouse=True)
def _ensure_schema() -> None:
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
