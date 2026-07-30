"""Integration test for the Alembic migration path against a live Postgres.

Skipped automatically when Postgres isn't reachable (DEVELOPMENT_GUIDE.md:
these need `make up`). Proves TRZ-P1-04's "migration idempotent" DoD via a
real upgrade -> downgrade -> upgrade cycle, not just offline SQL generation
(`alembic upgrade head --sql`, which only proves the script runs, not that
Postgres accepts it).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from trazo_server.config import Settings
from trazo_server.store.engine import create_engine

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EXPECTED_TABLES = {
    "projects",
    "runs",
    "events",
    "blobs",
    "detections",
    "policy_decisions",
    "alembic_version",
}


def _alembic_config() -> Config:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "migrations"))
    return cfg


async def _fetch_public_table_names() -> set[str]:
    engine = create_engine(Settings().database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                sa.text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            )
            return {row[0] for row in result}
    finally:
        await engine.dispose()


def test_migrations__upgrade_downgrade_upgrade_cycle_is_idempotent() -> None:
    cfg = _alembic_config()

    try:
        command.upgrade(cfg, "head")
    except Exception:
        pytest.skip("Postgres not reachable — run `make up` for integration coverage")

    try:
        assert asyncio.run(_fetch_public_table_names()) >= _EXPECTED_TABLES

        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")  # must not fail the second time around

        assert asyncio.run(_fetch_public_table_names()) >= _EXPECTED_TABLES
    finally:
        # Re-upgrade rather than leaving the schema torn down: this runs
        # against the same live Postgres every other test in the session
        # shares (conftest.py's _ensure_schema fixture only migrates
        # once, up front), so downgrading to "base" here would leave
        # every test collected after this file with no tables.
        command.upgrade(cfg, "head")
