"""The policy endpoint against a live, migrated Postgres (ADR-006).

test_api_policy.py already covers this endpoint's behaviour against
InMemoryTraceStore. That fake has no foreign key, so it cannot reproduce
the failure this file exists for: `events.run_id` REFERENCES `runs`, and
the policy endpoint is synchronous while `run.started` reaches the store
asynchronously (SDK -> batched POST -> Redis Streams -> StoreWorker). For
a run's *first* governed action the decision write routinely arrives
before the run row exists, which used to raise ForeignKeyViolationError,
500 the endpoint, and -- because the SDK's fail-open path treats a failed
evaluation as "allow" -- let the governed action execute unchecked.

Skipped automatically when Postgres isn't reachable, same as
test_trace_store_postgres.py.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from trazo_server.api.deps import get_event_bus, get_opa_client, get_trace_store
from trazo_server.app import create_app
from trazo_server.bus.memory import InMemoryEventBus
from trazo_server.config import Settings
from trazo_server.policy.opa_client import FakeOpaClient
from trazo_server.store.engine import create_engine
from trazo_server.store.postgres_trace_store import PostgresTraceStore

_REPO_ROOT = Path(__file__).resolve().parents[1]
_API_KEY = "test-key"
_FINGERPRINT = "sha256:" + "a" * 64


def _alembic_config() -> Config:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "migrations"))
    return cfg


@pytest.fixture(scope="module", autouse=True)
def _skip_without_postgres() -> None:
    try:
        command.upgrade(_alembic_config(), "head")
    except Exception:
        pytest.skip("Postgres not reachable — run `make up` for integration coverage")


@pytest.fixture
def opa() -> FakeOpaClient:
    return FakeOpaClient()


@pytest.fixture
def client(tmp_path: Path, opa: FakeOpaClient) -> Iterator[TestClient]:
    settings = Settings(
        api_key=_API_KEY,
        blob_root=str(tmp_path / "blobs"),
        feature_store_worker=False,
        feature_detector_worker=False,
    )
    engine = create_engine(settings.database_url)
    app = create_app(settings)
    app.dependency_overrides[get_opa_client] = lambda: opa
    app.dependency_overrides[get_trace_store] = lambda: PostgresTraceStore(engine)
    app.dependency_overrides[get_event_bus] = lambda: InMemoryEventBus()
    with TestClient(app) as test_client:
        yield test_client


def test_evaluate__records_a_decision_for_a_run_whose_run_started_has_not_landed(
    client: TestClient, opa: FakeOpaClient
) -> None:
    """The regression: a deny for a brand-new run_id the store has never
    seen. Before the placeholder-run write this returned 500, and the SDK
    failed open -- so the very first tool call of every run that outran its
    own `run.started` executed without governance.
    """
    opa.next_result = {
        "decision": "deny",
        "policy_id": "cost_cap",
        "reasons": ["over budget"],
    }
    unseen_run_id = f"run_{uuid.uuid4().hex[:12]}"

    response = client.post(
        "/v1/policy/evaluate",
        json={
            "run_id": unseen_run_id,
            "project": "research-assistant",
            "mode": "enforce",
            "action": {
                "kind": "tool.call",
                "fingerprint": _FINGERPRINT,
                "tool_name": "web_search",
                "side_effect_class": "read",
                "projected_cost_usd": 0.1,
            },
            "run_context": {"cost_usd_so_far": 99.0, "active_detections": []},
        },
        headers={"Authorization": f"Bearer {_API_KEY}"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["decision"] == "deny"

    # And the decision is actually durable, which is the whole point of
    # recording it before responding (ADR-006).
    events = client.get(f"/v1/runs/{unseen_run_id}/events").json()["events"]
    assert [e["kind"] for e in events] == ["policy.decision"]
    assert events[0]["payload"]["policy_id"] == "cost_cap"
