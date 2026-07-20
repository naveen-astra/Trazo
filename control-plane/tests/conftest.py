"""Shared pytest fixtures for control-plane tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from trazo_server.app import create_app
from trazo_server.config import Settings


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A TestClient with the lifespan run, so app.state (event_bus, blob_store,
    engine) is populated — required by anything beyond /healthz /readyz /metrics.
    The in-process store worker is off: it has no real Redis/Postgres to poll
    under TestClient, and its own behavior is unit-tested in
    test_store_worker.py against fakes."""
    settings = Settings(feature_store_worker=False)
    with TestClient(create_app(settings)) as test_client:
        yield test_client
