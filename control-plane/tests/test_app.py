"""Ops-endpoint tests for the app factory (TRZ-P0-02/03, TRZ-P1-08)."""

from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient

from trazo_server.app import create_app
from trazo_server.config import Settings


def test_app__store_worker_enabled_starts_and_stops_cleanly_without_redis() -> None:
    """TRZ-P1-06: the in-process worker task must not crash app startup or
    shutdown even when Redis is unreachable (run_forever catches and logs
    per-iteration errors) — a transient infra hiccup must not take the
    whole control plane down with it."""
    settings = Settings(feature_store_worker=True)
    with TestClient(create_app(settings)) as test_client:
        response = test_client.get("/healthz")
        assert response.status_code == 200


def test_app__detector_worker_enabled_starts_and_stops_cleanly_without_redis() -> None:
    """Same DoD as the store-worker case above, for the detector worker
    (TRZ-P5-06): a transient infra hiccup must not take the whole control
    plane down with it."""
    settings = Settings(feature_detector_worker=True)
    with TestClient(create_app(settings)) as test_client:
        response = test_client.get("/healthz")
        assert response.status_code == 200


def test_healthz__returns_ok_and_version(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]


def test_readyz__reports_not_ready_without_live_dependencies(
    client: TestClient,
) -> None:
    """TRZ-P1-08: /readyz now does real Postgres/Redis checks (ARCHITECTURE
    §8) — under TestClient, with no live services, both must report
    'error' and the endpoint must answer 503, not silently claim ready."""
    response = client.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"] == {"postgres": "error", "redis": "error"}


class _FakeConn:
    async def execute(self, *_args: object, **_kwargs: object) -> None:
        return None


class _FakeEngine:
    @asynccontextmanager
    async def connect(self) -> Any:
        yield _FakeConn()


class _FakeRedis:
    async def ping(self) -> bool:
        return True


def test_readyz__reports_ready_when_dependencies_are_reachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(feature_store_worker=False)
    with TestClient(create_app(settings)) as test_client:
        app = test_client.app
        # AsyncEngine/redis.asyncio.Redis attributes aren't monkeypatchable
        # directly (read-only descriptors) — swap the whole objects on
        # app.state instead of patching their methods.
        monkeypatch.setattr(app.state, "engine", _FakeEngine())
        monkeypatch.setattr(app.state, "redis_client", _FakeRedis())

        response = test_client.get("/readyz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"postgres": "ok", "redis": "ok"}


def test_metrics__exposes_prometheus_text(client: TestClient) -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
