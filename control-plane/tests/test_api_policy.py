"""Integration tests for the policy API (API_SPEC.md "Policy", ADR-006).

OPA is swapped for FakeOpaClient via a FastAPI dependency override so
these run without a live OPA sidecar — the real HTTP contract is covered
separately in test_opa_client.py/test_opa_client_integration.py.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trazo_server.api.deps import get_event_bus, get_opa_client, get_trace_store
from trazo_server.app import create_app
from trazo_server.bus.memory import InMemoryEventBus
from trazo_server.config import Settings
from trazo_server.policy.opa_client import FakeOpaClient
from trazo_server.store.memory_trace_store import InMemoryTraceStore

_API_KEY = "test-key"
_FINGERPRINT = "sha256:" + "a" * 64


@pytest.fixture
def opa() -> FakeOpaClient:
    return FakeOpaClient()


@pytest.fixture
def trace_store() -> InMemoryTraceStore:
    return InMemoryTraceStore()


@pytest.fixture
def bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture
def client(
    tmp_path: Path,
    opa: FakeOpaClient,
    trace_store: InMemoryTraceStore,
    bus: InMemoryEventBus,
) -> Iterator[TestClient]:
    settings = Settings(
        api_key=_API_KEY,
        blob_root=str(tmp_path / "blobs"),
        feature_store_worker=False,
        feature_detector_worker=False,
    )
    app = create_app(settings)
    app.dependency_overrides[get_opa_client] = lambda: opa
    app.dependency_overrides[get_trace_store] = lambda: trace_store
    app.dependency_overrides[get_event_bus] = lambda: bus
    with TestClient(app) as test_client:
        yield test_client


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_API_KEY}"}


def _request_body(**overrides: object) -> dict:
    body: dict = {
        "run_id": "run_1",
        "project": "research-assistant",
        "mode": "enforce",
        "action": {
            "kind": "tool.call",
            "fingerprint": _FINGERPRINT,
            "tool_name": "web_search",
            "side_effect_class": "read",
            "projected_cost_usd": 0.1,
        },
        "run_context": {"cost_usd_so_far": 0.5, "active_detections": []},
    }
    body.update(overrides)
    return body


def test_evaluate__returns_the_opa_decision(
    client: TestClient, opa: FakeOpaClient
) -> None:
    opa.next_result = {"decision": "deny", "policy_id": "cost_cap", "reasons": ["x"]}

    response = client.post(
        "/v1/policy/evaluate", json=_request_body(), headers=_auth_headers()
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "deny"
    assert body["policy_id"] == "cost_cap"
    assert body["reasons"] == ["x"]
    assert body["eval_ms"] >= 0


def test_evaluate__records_a_policy_decision_event_before_responding(
    client: TestClient, opa: FakeOpaClient, trace_store: InMemoryTraceStore
) -> None:
    opa.next_result = {"decision": "deny", "policy_id": "cost_cap", "reasons": ["x"]}

    client.post("/v1/policy/evaluate", json=_request_body(), headers=_auth_headers())

    [event] = trace_store._events.values()  # type: ignore[attr-defined]
    assert event.kind == "policy.decision"
    assert event.run_id == "run_1"
    assert event.payload["decision"] == "deny"
    assert event.payload["policy_id"] == "cost_cap"
    assert event.payload["action_ref"] == {
        "fingerprint": _FINGERPRINT,
        "kind": "tool.call",
    }
    assert event.payload["mode"] == "enforce"


async def test_evaluate__republishes_the_decision_onto_events_stream(
    client: TestClient, opa: FakeOpaClient, bus: InMemoryEventBus
) -> None:
    import json

    from trazo_server.topics import EVENTS_STREAM

    opa.next_result = {"decision": "deny", "policy_id": "cost_cap", "reasons": ["x"]}

    client.post("/v1/policy/evaluate", json=_request_body(), headers=_auth_headers())

    await bus.ensure_group(EVENTS_STREAM, "test-reader")
    [message] = await bus.read_group(
        EVENTS_STREAM, "test-reader", "consumer-1", count=10, block_ms=0
    )
    published = json.loads(message.fields["event"])
    assert published["kind"] == "policy.decision"
    assert published["project"] == "research-assistant"


def test_evaluate__passes_the_action_and_run_context_through_to_opa(
    client: TestClient, opa: FakeOpaClient
) -> None:
    client.post(
        "/v1/policy/evaluate",
        json=_request_body(
            run_context={"cost_usd_so_far": 3.2, "active_detections": ["loop"]}
        ),
        headers=_auth_headers(),
    )

    [input_doc] = opa.calls
    assert input_doc["run_id"] == "run_1"
    assert input_doc["run_context"]["cost_usd_so_far"] == 3.2
    assert input_doc["run_context"]["active_detections"] == ["loop"]
    assert input_doc["action"]["tool_name"] == "web_search"


def test_evaluate__503_when_opa_is_unavailable(
    client: TestClient, opa: FakeOpaClient, trace_store: InMemoryTraceStore
) -> None:
    opa.raise_unavailable = True

    response = client.post(
        "/v1/policy/evaluate", json=_request_body(), headers=_auth_headers()
    )

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert trace_store._events == {}  # type: ignore[attr-defined]


def test_evaluate__creates_the_run_row_when_run_started_has_not_landed_yet(
    client: TestClient, opa: FakeOpaClient, trace_store: InMemoryTraceStore
) -> None:
    """`events.run_id` is a foreign key, and this endpoint is synchronous
    while `run.started` reaches the store asynchronously -- so for a run's
    first governed action, the decision write routinely arrives first. It
    has to create the run row itself or the insert violates the FK, 500s,
    and the SDK fails open: governance silently off exactly when a run is
    new. (The FK itself only exists in Postgres, so the assertion here is
    on the fix's contract -- that the row gets created -- with
    test_trace_store_postgres.py covering the constraint for real.)
    """
    opa.next_result = {"decision": "deny", "policy_id": "cost_cap", "reasons": ["x"]}

    response = client.post(
        "/v1/policy/evaluate", json=_request_body(), headers=_auth_headers()
    )

    assert response.status_code == 200
    run = trace_store._runs["run_1"]  # type: ignore[attr-defined]
    assert run.project_id in trace_store._projects  # type: ignore[attr-defined]
    # A stand-in until run.started lands and reclaims it (upsert_run's
    # `authoritative`) -- deliberately not guessed at here.
    assert run.framework == "unknown"


def test_evaluate__requires_the_bearer_api_key(client: TestClient) -> None:
    response = client.post("/v1/policy/evaluate", json=_request_body())

    assert response.status_code == 401


def test_evaluate__rejects_a_malformed_fingerprint(client: TestClient) -> None:
    response = client.post(
        "/v1/policy/evaluate",
        json=_request_body(
            action={
                "kind": "tool.call",
                "fingerprint": "not-a-real-fingerprint",
                "tool_name": "web_search",
                "side_effect_class": "read",
                "projected_cost_usd": 0.1,
            }
        ),
        headers=_auth_headers(),
    )

    assert response.status_code == 422
