"""Ops-endpoint tests for the Phase 0 stub app (TRZ-P0-02/03)."""

from fastapi.testclient import TestClient

from trazo_server.app import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_healthz__returns_ok_and_version() -> None:
    response = _client().get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]


def test_readyz__returns_ready() -> None:
    response = _client().get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_metrics__exposes_prometheus_text() -> None:
    response = _client().get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
