"""Integration tests for the ingest API (API_SPEC.md "Ingest").

The event bus is swapped for InMemoryEventBus via a FastAPI dependency
override so these run without live Redis — the bus's own Redis Streams
mechanics are covered separately in test_bus_redis_streams.py. The blob
store is a real FilesystemBlobStore pointed at tmp_path (pure filesystem,
nothing to fake).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trazo_server.api.deps import get_event_bus
from trazo_server.app import create_app
from trazo_server.bus.memory import InMemoryEventBus
from trazo_server.config import Settings
from trazo_server.topics import EVENTS_STREAM

_API_KEY = "test-key"


@pytest.fixture
def bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture
def client(tmp_path: Path, bus: InMemoryEventBus) -> Iterator[TestClient]:
    settings = Settings(
        api_key=_API_KEY,
        blob_root=str(tmp_path / "blobs"),
        # Both off: no real Redis/Postgres under TestClient, and a worker left
        # running against CI's live service containers blocks teardown.
        feature_store_worker=False,
        feature_detector_worker=False,
    )
    app = create_app(settings)
    app.dependency_overrides[get_event_bus] = lambda: bus
    with TestClient(app) as test_client:
        yield test_client


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_API_KEY}"}


def _sample_event(**overrides: object) -> dict:
    event: dict = {
        "schema": "trazo.v1",
        "event_id": "evt_01J9Z8QK3V0000000000000000",
        "run_id": "run_01J9Z8QK3V7XG2N4P5R6S7T8VW",
        "project": "research-assistant",
        "seq": 0,
        "ts": "2026-07-18T09:30:00.000Z",
        "kind": "run.started",
        "payload": {
            "framework": "langgraph",
            "framework_version": "0.2.39",
            "sdk_version": "0.1.0",
            "entry_input": {"query": "hi"},
            "tags": {},
        },
    }
    event.update(overrides)
    return event


async def _published_messages(bus: InMemoryEventBus) -> list[str]:
    await bus.ensure_group(EVENTS_STREAM, "test-verify")
    messages = await bus.read_group(
        EVENTS_STREAM, "test-verify", "test-consumer", count=100, block_ms=0
    )
    return [m.fields["event"] for m in messages]


def test_ingest_events__rejects_request_without_auth(client: TestClient) -> None:
    response = client.post("/v1/ingest/events", json={"events": [_sample_event()]})

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["title"] == "Unauthorized"


def test_ingest_events__rejects_wrong_bearer_key(client: TestClient) -> None:
    response = client.post(
        "/v1/ingest/events",
        json={"events": [_sample_event()]},
        headers={"Authorization": "Bearer not-the-key"},
    )

    assert response.status_code == 401


async def test_ingest_events__accepts_valid_batch_and_publishes_to_bus(
    client: TestClient, bus: InMemoryEventBus
) -> None:
    response = client.post(
        "/v1/ingest/events",
        json={"events": [_sample_event()]},
        headers=_auth_headers(),
    )

    assert response.status_code == 202
    assert response.json() == {"accepted": 1, "rejected": []}

    published = await _published_messages(bus)
    assert len(published) == 1
    assert '"kind":"run.started"' in published[0]


async def test_ingest_events__partial_batch_reports_per_index_rejection(
    client: TestClient, bus: InMemoryEventBus
) -> None:
    valid = _sample_event(seq=0)
    # missing required fingerprint + llm.call-specific payload fields
    invalid = _sample_event(seq=1, kind="llm.call")

    response = client.post(
        "/v1/ingest/events",
        json={"events": [valid, invalid]},
        headers=_auth_headers(),
    )

    assert response.status_code == 202
    body = response.json()
    assert body["accepted"] == 1
    assert len(body["rejected"]) == 1
    assert body["rejected"][0]["index"] == 1

    published = await _published_messages(bus)
    assert len(published) == 1


def test_ingest_events__batch_over_limit_rejected_with_413(client: TestClient) -> None:
    events = [_sample_event(seq=i) for i in range(501)]

    response = client.post(
        "/v1/ingest/events", json={"events": events}, headers=_auth_headers()
    )

    assert response.status_code == 413
    assert response.json()["title"] == "Batch Too Large"


def test_ingest_blobs__stores_and_returns_matching_sha256(client: TestClient) -> None:
    data = b"hello blob world"
    digest = hashlib.sha256(data).hexdigest()

    response = client.post(
        "/v1/ingest/blobs",
        content=data,
        headers={
            **_auth_headers(),
            "Content-Type": "text/plain",
            "X-Trazo-Sha256": f"sha256:{digest}",
        },
    )

    assert response.status_code == 201
    assert response.json() == {"sha256": f"sha256:{digest}"}


def test_ingest_blobs__is_idempotent_by_content(client: TestClient) -> None:
    data = b"idempotent bytes"
    digest = hashlib.sha256(data).hexdigest()
    headers = {
        **_auth_headers(),
        "Content-Type": "text/plain",
        "X-Trazo-Sha256": f"sha256:{digest}",
    }

    first = client.post("/v1/ingest/blobs", content=data, headers=headers)
    second = client.post("/v1/ingest/blobs", content=data, headers=headers)

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()


def test_ingest_blobs__checksum_mismatch_returns_409(client: TestClient) -> None:
    data = b"real bytes"
    wrong_digest = hashlib.sha256(b"different bytes").hexdigest()

    response = client.post(
        "/v1/ingest/blobs",
        content=data,
        headers={
            **_auth_headers(),
            "Content-Type": "text/plain",
            "X-Trazo-Sha256": f"sha256:{wrong_digest}",
        },
    )

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"


def test_ingest_blobs__rejects_request_without_auth(client: TestClient) -> None:
    response = client.post(
        "/v1/ingest/blobs",
        content=b"x",
        headers={"X-Trazo-Sha256": "sha256:" + "0" * 64},
    )

    assert response.status_code == 401
