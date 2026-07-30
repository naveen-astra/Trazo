"""Shared pytest fixtures for control-plane tests."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from trazo_server.app import create_app
from trazo_server.config import Settings

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config() -> Config:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "migrations"))
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _ensure_schema() -> None:
    """Applies migrations once, before any test in the whole session runs.

    Without this, schema application was only module-scoped inside
    test_trace_store_postgres.py — fine as long as nothing Postgres-backed
    ran before that file, which held only because every earlier-collected
    test either avoided a real Postgres store or (test_app.py's now-fixed
    blob_root bug) errored out before reaching one. Once that masking bug
    was fixed, test_app.py's real-worker tests ran against a completely
    unmigrated database (pytest collects files alphabetically, and 'app'
    sorts before 'migrations'/'trace_store_postgres'): every query hit
    "relation \"runs\" does not exist", and the store/detector worker's
    run_forever() — designed to retry forever through what it assumes is
    a transient bus/store hiccup (ARCHITECTURE.md §7) — spun on that
    permanent error for the rest of the CI job.

    Fails open (swallows the exception) rather than skipping: this is
    session-scoped autouse, so a bare pytest.skip() here would skip every
    test in the run, including the many that never touch Postgres at all.
    Individual Postgres-backed tests/fixtures keep their own
    reachability skip (test_migrations.py, test_trace_store_postgres.py's
    module fixture) for a Postgres-less local run."""
    with contextlib.suppress(Exception):
        command.upgrade(_alembic_config(), "head")


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """A TestClient with the lifespan run, so app.state (event_bus, blob_store,
    engine) is populated — required by anything beyond /healthz /readyz /metrics.
    The in-process store/detector workers are off: neither has a real
    Redis/Postgres to poll under TestClient, and each is unit-tested on its
    own against fakes (test_store_worker.py, test_detector_worker.py).
    blob_root is repointed at tmp_path: the default (/var/lib/trazo/blobs,
    a container path) isn't writable by the unprivileged user CI runs
    tests as, and FilesystemBlobStore.__init__ mkdir()s it eagerly."""
    settings = Settings(
        feature_store_worker=False,
        feature_detector_worker=False,
        blob_root=str(tmp_path / "blobs"),
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client
