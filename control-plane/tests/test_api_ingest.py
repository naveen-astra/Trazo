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
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trazo_server.api.deps import get_event_bus, get_trace_store
from trazo_server.app import create_app
from trazo_server.bus.memory import InMemoryEventBus
from trazo_server.config import Settings
from trazo_server.store.memory_trace_store import InMemoryTraceStore
from trazo_server.store.rows import RunRow
from trazo_server.topics import EVENTS_STREAM

_API_KEY = "test-key"
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture
def trace_store() -> InMemoryTraceStore:
    return InMemoryTraceStore()


@pytest.fixture
def client(
    tmp_path: Path, bus: InMemoryEventBus, trace_store: InMemoryTraceStore
) -> Iterator[TestClient]:
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
    app.dependency_overrides[get_trace_store] = lambda: trace_store
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


def _report_body(**overrides: object) -> dict:
    body: dict = {
        "boundary_fidelity": 1.0,
        "state_fidelity": 1.0,
        "matched": 2,
        "reordered": 0,
        "divergences": [],
        "replay_overhead": 0.42,
    }
    body.update(overrides)
    return body


async def test_submit_replay_report__persists_and_is_readable_back(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    """The exact round trip `trazo verify` -> POST -> GET depends on: a
    real replay result submitted by the SDK shows up for the dashboard's
    Replay Studio, not a fixture."""
    await trace_store.upsert_run(
        RunRow(
            run_id="run_1",
            project_id="proj_1",
            framework="langgraph",
            status="ok",
            started_at=_NOW,
            finished_at=None,
            tags={},
            totals={},
        )
    )

    response = client.post(
        "/v1/runs/run_1/replay-report",
        json=_report_body(),
        headers=_auth_headers(),
    )
    assert response.status_code == 204

    fetched = client.get("/v1/runs/run_1/replay-report")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["boundary_fidelity"] == 1.0
    assert body["replay_overhead"] == 0.42
    assert body["divergences"] == []


def test_submit_replay_report__404_for_unknown_run(client: TestClient) -> None:
    response = client.post(
        "/v1/runs/run_does_not_exist/replay-report",
        json=_report_body(),
        headers=_auth_headers(),
    )

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


def test_submit_replay_report__rejects_request_without_auth(client: TestClient) -> None:
    response = client.post("/v1/runs/run_1/replay-report", json=_report_body())

    assert response.status_code == 401


def test_get_replay_report__404_when_never_verified(client: TestClient) -> None:
    response = client.get("/v1/runs/run_never_verified/replay-report")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


async def test_submit_replay_report__resubmission_replaces_not_accumulates(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    await trace_store.upsert_run(
        RunRow(
            run_id="run_1",
            project_id="proj_1",
            framework="langgraph",
            status="ok",
            started_at=_NOW,
            finished_at=None,
            tags={},
            totals={},
        )
    )

    client.post(
        "/v1/runs/run_1/replay-report",
        json=_report_body(
            boundary_fidelity=0.5,
            divergences=[
                {
                    "kind": "tool.call",
                    "reason": "fingerprint mismatch",
                    "expected_seq": 1,
                    "expected_event_id": "evt_1",
                    "expected_fingerprint": "sha256:" + "a" * 64,
                    "live_fingerprint": "sha256:" + "b" * 64,
                }
            ],
        ),
        headers=_auth_headers(),
    )
    client.post(
        "/v1/runs/run_1/replay-report",
        json=_report_body(boundary_fidelity=1.0, divergences=[]),
        headers=_auth_headers(),
    )

    fetched = client.get("/v1/runs/run_1/replay-report").json()
    assert fetched["boundary_fidelity"] == 1.0
    assert fetched["divergences"] == []
