"""Server-side events must never overwrite events the SDK has already
numbered but not yet delivered. Reproduction of the corruption observed
live on 2026-10-16: a loop-chaos run whose SDK sent 135 events kept only
134, because a detection minted the next sequence number (max persisted
+ 1) while the SDK's own event with that number was still in flight, and
the store's upsert then overwrote one with the other.
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
_NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module", autouse=True)
def _skip_without_postgres() -> None:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "migrations"))
    try:
        command.upgrade(cfg, "head")
    except Exception:
        pytest.skip("Postgres not reachable — run `make up` for integration coverage")


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_engine(Settings().database_url)
    yield eng
    await eng.dispose()


def _sdk_event(run_id: str, seq: int) -> EventRow:
    return EventRow(
        run_id=run_id,
        seq=seq,
        event_id=f"evt_sdk_{seq:04d}",
        kind="step.started",
        ts=_NOW,
        step_id=None,
        agent_id=None,
        fingerprint=None,
        payload={"name": f"step-{seq}"},
        blobs=[],
    )


async def test_server_event_does_not_overwrite_an_in_flight_sdk_event(
    engine: AsyncEngine,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    project_id, run_id = f"proj_{suffix}", f"run_{suffix}"
    store = PostgresTraceStore(engine)
    await store.ensure_project(project_id, f"test-{project_id}")
    await store.upsert_run(
        RunRow(
            run_id=run_id,
            project_id=project_id,
            framework="langgraph",
            status="running",
            started_at=_NOW,
            finished_at=None,
            tags={},
            totals={},
        )
    )

    # The SDK has emitted seq 0..5. Only 0..2 have been persisted so far;
    # 3..5 are still in the shipper buffer or on the bus.
    await store.upsert_events([_sdk_event(run_id, seq) for seq in range(3)])

    # The detector, reacting to seq 2, records a detection.
    await store.append_server_event(
        run_id=run_id,
        project=f"test-{project_id}",
        after_seq=2,
        event_id=f"evt_detection_{suffix}",
        kind="detection.raised",
        ts=_NOW,
        payload={"detector": "loop"},
    )

    # The in-flight SDK events land.
    await store.upsert_events([_sdk_event(run_id, seq) for seq in range(3, 6)])

    stored = await store.get_events(run_id, limit=100)
    stored_ids = {row.event_id for row in stored}
    assert {f"evt_sdk_{seq:04d}" for seq in range(6)} <= stored_ids, (
        "an SDK event was overwritten"
    )
    assert f"evt_detection_{suffix}" in stored_ids, "the detection was overwritten"
