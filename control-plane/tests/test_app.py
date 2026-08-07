"""Ops-endpoint tests for the app factory (TRZ-P0-02/03, TRZ-P1-08)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from trazo_server.app import create_app
from trazo_server.bus.protocol import BUS_BLOCK_MS, BUS_SOCKET_TIMEOUT_SECONDS
from trazo_server.config import Settings

# Deliberately unreachable rather than relying on ambient absence: CI's
# `python` job env-points Settings' defaults at real, live Postgres/Redis
# service containers for every step, so "nothing's listening" is false
# there (same trap test_readyz__reports_not_ready_without_live_dependencies
# hit below). Worse than a wrong assertion here, though — a *real* worker
# left running against genuinely-reachable infra blocks in its blocking
# bus read (StoreWorker.run_forever's poll_block_ms) and cancelling it
# during TestClient teardown was observed taking 60s+ against GitHub's
# runners specifically (not reproducible against a local Postgres/Redis)
# until pytest-timeout killed the test — so this isn't just about
# asserting the right thing, it's what keeps these two tests fast at all.
_UNREACHABLE_DATABASE_URL = "postgresql://trazo:trazo@localhost:1/trazo"
_UNREACHABLE_REDIS_URL = "redis://localhost:1/0"


def test_app__store_worker_enabled_starts_and_stops_cleanly_without_redis(
    tmp_path: Path,
) -> None:
    """TRZ-P1-06: the in-process worker task must not crash app startup or
    shutdown even when Redis is unreachable (run_forever catches and logs
    per-iteration errors) — a transient infra hiccup must not take the
    whole control plane down with it."""
    settings = Settings(
        feature_store_worker=True,
        feature_detector_worker=False,
        database_url=_UNREACHABLE_DATABASE_URL,
        redis_url=_UNREACHABLE_REDIS_URL,
        blob_root=str(tmp_path / "blobs"),
    )
    with TestClient(create_app(settings)) as test_client:
        response = test_client.get("/healthz")
        assert response.status_code == 200


def test_app__detector_worker_enabled_starts_and_stops_cleanly_without_redis(
    tmp_path: Path,
) -> None:
    """Same DoD as the store-worker case above, for the detector worker
    (TRZ-P5-06): a transient infra hiccup must not take the whole control
    plane down with it."""
    settings = Settings(
        feature_store_worker=False,
        feature_detector_worker=True,
        database_url=_UNREACHABLE_DATABASE_URL,
        redis_url=_UNREACHABLE_REDIS_URL,
        blob_root=str(tmp_path / "blobs"),
    )
    with TestClient(create_app(settings)) as test_client:
        response = test_client.get("/healthz")
        assert response.status_code == 200


def test_healthz__returns_ok_and_version(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]


class _FakeConn:
    async def execute(self, *_args: object, **_kwargs: object) -> None:
        return None


class _FakeEngine:
    @asynccontextmanager
    async def connect(self) -> Any:
        yield _FakeConn()


class _RaisingEngine:
    @asynccontextmanager
    async def connect(self) -> AsyncIterator[Any]:
        raise ConnectionError("postgres unreachable")
        yield  # pragma: no cover — unreachable, satisfies the generator type


class _FakeRedis:
    async def ping(self) -> bool:
        return True


class _RaisingRedis:
    async def ping(self) -> bool:
        raise ConnectionError("redis unreachable")


def test_readyz__reports_not_ready_without_live_dependencies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """TRZ-P1-08: /readyz does real Postgres/Redis checks (ARCHITECTURE
    §8) — when neither is reachable, both must report 'error' and the
    endpoint must answer 503, not silently claim ready. Uses fakes that
    raise rather than an ambiently-unreachable database_url/redis_url:
    CI's own `python` job env-points Settings' defaults at real service
    containers for every step, so relying on "nothing's listening" isn't
    actually true there (or on a dev machine with Postgres/Redis running
    locally for something else) — this must fail the same way regardless
    of what else happens to be reachable on the host. Both worker flags
    are off: this test only cares about the readyz handler's own logic,
    and a real worker started against CI's live service containers (the
    handler's own engine/redis_client get monkeypatched below, but a
    worker builds and uses its own bus/store independently) has separately
    been observed to make TestClient teardown take 60s+ against GitHub's
    runners specifically."""
    settings = Settings(
        feature_store_worker=False,
        feature_detector_worker=False,
        blob_root=str(tmp_path / "blobs"),
    )
    with TestClient(create_app(settings)) as test_client:
        app = test_client.app
        monkeypatch.setattr(app.state, "engine", _RaisingEngine())
        monkeypatch.setattr(app.state, "redis_client", _RaisingRedis())

        response = test_client.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"] == {"postgres": "error", "redis": "error"}


def test_readyz__reports_ready_when_dependencies_are_reachable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Both worker flags off, same reason as the not-ready case above: this
    # test only cares about the readyz handler's own (monkeypatched) logic.
    settings = Settings(
        feature_store_worker=False,
        feature_detector_worker=False,
        blob_root=str(tmp_path / "blobs"),
    )
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


def test_metrics__documented_path_serves_directly_without_a_redirect(
    client: TestClient,
) -> None:
    """API_SPEC.md names `GET /metrics`, and that exact path must return
    the exposition itself.

    Found by running scripts/smoke/phase1.sh against a live stack: with
    /metrics *mounted*, Starlette answered the documented path with a 307
    to /metrics/, so the smoke's plain `curl -fsS` got an empty body and
    its DLQ-depth assertion failed on a metric that was in fact present
    and zero. The test above could not catch it — TestClient follows
    redirects by default, so a 307 still reads as 200 there.
    """
    response = client.get("/metrics", follow_redirects=False)

    assert response.status_code == 200
    assert "trazo_bus_dlq_depth_messages" in response.text


def test_cors__preflight_from_the_dashboard_origin_is_allowed(
    client: TestClient,
) -> None:
    """Found running the real dashboard against a real compose stack in a
    real browser (no CORS middleware at all — every fetch from the
    dashboard's own origin to the control plane's was silently blocked;
    the dashboard's live-browser verification up to this point had only
    ever run against a same-origin stdlib mock, never the real cross-
    origin compose layout). Confirmed by hand first: a real preflight
    against this app returned 405, not a CORS response, before the fix."""
    response = client.options(
        "/v1/runs",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_cors__actual_get_response_carries_the_allow_origin_header(
    client: TestClient,
) -> None:
    response = client.get("/healthz", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_redis_client__socket_timeout_exceeds_the_worker_poll_block() -> None:
    """The paired-timeout invariant, asserted rather than assumed.

    XREADGROUP's `block` is a server-side wait; socket_timeout is the
    client's patience for that same command's reply. If the client's is
    not strictly longer, every idle poll races and usually loses — and a
    batch delivered right at the boundary lands in the group's pending
    list with the client never reading the reply, stranding it.

    That is not hypothetical: redis-py 8 defaults socket_timeout to 5s
    while the workers blocked for exactly 5s, which wedged the store
    worker completely (167 pending, unacked messages, nothing persisted).
    A silent dependency-default change caused it, so the relationship is
    pinned here instead of living only in a comment.
    """
    assert BUS_SOCKET_TIMEOUT_SECONDS > BUS_BLOCK_MS / 1000
