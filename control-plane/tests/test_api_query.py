"""Integration tests for the query API (API_SPEC.md "Query").

TraceStore is swapped for InMemoryTraceStore via a FastAPI dependency
override so these run without live Postgres; keyset-pagination
correctness itself is proven at the store level in
test_trace_store_memory.py. These tests exercise the same guarantee
end-to-end through the actual HTTP endpoints, plus routing/validation
concerns (404s, invalid cursor/limit, unauthenticated access).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trazo_server.api.deps import get_trace_store
from trazo_server.app import create_app
from trazo_server.config import Settings
from trazo_server.store.memory_trace_store import InMemoryTraceStore
from trazo_server.store.rows import DetectionRow, EventRow, PolicyDecisionRow, RunRow

_NOW = datetime(2026, 7, 18, 9, 30, tzinfo=timezone.utc)


@pytest.fixture
def trace_store() -> InMemoryTraceStore:
    return InMemoryTraceStore()


@pytest.fixture
def client(tmp_path: Path, trace_store: InMemoryTraceStore) -> Iterator[TestClient]:
    settings = Settings(blob_root=str(tmp_path / "blobs"), feature_store_worker=False)
    app = create_app(settings)
    app.dependency_overrides[get_trace_store] = lambda: trace_store
    with TestClient(app) as test_client:
        yield test_client


def _run(**overrides: object) -> RunRow:
    defaults: dict[str, object] = {
        "run_id": "run_1",
        "project_id": "proj_1",
        "framework": "langgraph",
        "status": "running",
        "started_at": _NOW,
        "finished_at": None,
        "tags": {},
        "totals": {},
    }
    defaults.update(overrides)
    return RunRow(**defaults)  # type: ignore[arg-type]


def _event(**overrides: object) -> EventRow:
    defaults: dict[str, object] = {
        "run_id": "run_1",
        "seq": 0,
        "event_id": "evt_1",
        "kind": "run.started",
        "ts": _NOW,
        "step_id": None,
        "agent_id": None,
        "fingerprint": None,
        "payload": {},
        "blobs": [],
    }
    defaults.update(overrides)
    return EventRow(**defaults)  # type: ignore[arg-type]


def _detection(**overrides: object) -> DetectionRow:
    defaults: dict[str, object] = {
        "detection_id": "det_1",
        "run_id": "run_1",
        "detector": "loop",
        "severity": "warn",
        "raised_at": _NOW,
        "evidence": [{"event_id": "evt_a"}],
        "details": {"repeat_count": 4},
    }
    defaults.update(overrides)
    return DetectionRow(**defaults)  # type: ignore[arg-type]


def _policy_decision(**overrides: object) -> PolicyDecisionRow:
    defaults: dict[str, object] = {
        "decision_id": "dec_1",
        "run_id": "run_1",
        "policy_id": "cost_cap",
        "action_kind": "tool.call",
        "action_fp": "sha256:" + "a" * 64,
        "decision": "deny",
        "mode": "enforce",
        "reasons": ["over cap"],
        "decided_at": _NOW,
        "eval_ms": 12.5,
    }
    defaults.update(overrides)
    return PolicyDecisionRow(**defaults)  # type: ignore[arg-type]


async def test_list_runs__returns_newest_first_and_respects_limit(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    for i in range(1, 4):
        await trace_store.upsert_run(
            _run(run_id=f"run_{i}", started_at=_NOW + timedelta(minutes=i))
        )

    response = client.get("/v1/runs", params={"limit": 2})

    assert response.status_code == 200
    body = response.json()
    assert [r["run_id"] for r in body["runs"]] == ["run_3", "run_2"]
    assert body["next_cursor"] is not None


async def test_list_runs__pagination_cursor_stable_under_concurrent_insert(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    for i in range(1, 5):  # run_1..run_4
        await trace_store.upsert_run(
            _run(run_id=f"run_{i}", started_at=_NOW + timedelta(minutes=i))
        )

    page1 = client.get("/v1/runs", params={"limit": 2}).json()
    assert [r["run_id"] for r in page1["runs"]] == ["run_4", "run_3"]

    # Concurrent insert of a brand-new, newer run between the two page fetches.
    await trace_store.upsert_run(
        _run(run_id="run_5", started_at=_NOW + timedelta(minutes=5))
    )

    page2 = client.get(
        "/v1/runs", params={"limit": 2, "cursor": page1["next_cursor"]}
    ).json()

    assert [r["run_id"] for r in page2["runs"]] == ["run_2", "run_1"]
    assert page2["next_cursor"] is None


def test_list_runs__invalid_cursor_returns_400_problem_details(
    client: TestClient,
) -> None:
    response = client.get("/v1/runs", params={"cursor": "not-a-valid-cursor!!"})

    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"


def test_list_runs__invalid_limit_returns_400(client: TestClient) -> None:
    response = client.get("/v1/runs", params={"limit": 0})

    assert response.status_code == 400


def test_list_runs__is_not_gated_by_bearer_auth(client: TestClient) -> None:
    """ADR-009: query/dashboard endpoints don't require the API key."""
    response = client.get("/v1/runs")

    assert response.status_code == 200


async def test_get_run__returns_full_row(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    await trace_store.upsert_run(_run(tags={"env": "demo"}))

    response = client.get("/v1/runs/run_1")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == "run_1"
    assert body["tags"] == {"env": "demo"}


def test_get_run__404_for_unknown_run(client: TestClient) -> None:
    response = client.get("/v1/runs/run_does_not_exist")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


async def test_list_events__orders_by_seq_and_paginates(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    await trace_store.upsert_events([_event(seq=2), _event(seq=0), _event(seq=1)])

    page1 = client.get("/v1/runs/run_1/events", params={"limit": 2}).json()
    assert [e["seq"] for e in page1["events"]] == [0, 1]
    assert page1["next_cursor"] is not None

    page2 = client.get(
        "/v1/runs/run_1/events",
        params={"limit": 2, "cursor": page1["next_cursor"]},
    ).json()
    assert [e["seq"] for e in page2["events"]] == [2]
    assert page2["next_cursor"] is None


async def test_list_events__filters_by_kind(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    await trace_store.upsert_events(
        [
            _event(seq=0, kind="run.started"),
            _event(seq=1, kind="llm.call"),
        ]
    )

    response = client.get("/v1/runs/run_1/events", params={"kind": "llm.call"})

    body = response.json()
    assert [e["seq"] for e in body["events"]] == [1]


async def test_list_detections__returns_most_recently_raised_first(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    await trace_store.upsert_run(_run())
    await trace_store.insert_detection(
        _detection(detection_id="det_older", raised_at=_NOW)
    )
    await trace_store.insert_detection(
        _detection(
            detection_id="det_newer",
            detector="budget",
            raised_at=_NOW + timedelta(minutes=1),
        )
    )

    response = client.get("/v1/runs/run_1/detections")

    body = response.json()
    assert [d["detection_id"] for d in body["detections"]] == [
        "det_newer",
        "det_older",
    ]
    assert body["detections"][0]["detector"] == "budget"


async def test_list_detections__empty_for_a_run_with_no_detections(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    await trace_store.upsert_run(_run())

    response = client.get("/v1/runs/run_1/detections")

    assert response.json() == {"detections": []}


def test_list_detections__404_for_unknown_run(client: TestClient) -> None:
    response = client.get("/v1/runs/run_missing/detections")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


async def test_list_policy_decisions__returns_most_recently_decided_first(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    await trace_store.upsert_run(_run())
    await trace_store.insert_policy_decision(
        _policy_decision(decision_id="dec_older", decided_at=_NOW)
    )
    await trace_store.insert_policy_decision(
        _policy_decision(
            decision_id="dec_newer",
            policy_id="tool_blocklist",
            decided_at=_NOW + timedelta(minutes=1),
        )
    )

    response = client.get("/v1/runs/run_1/policy-decisions")

    body = response.json()
    assert [d["decision_id"] for d in body["decisions"]] == [
        "dec_newer",
        "dec_older",
    ]
    assert body["decisions"][0]["policy_id"] == "tool_blocklist"


async def test_list_policy_decisions__empty_for_a_run_with_no_decisions(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    await trace_store.upsert_run(_run())

    response = client.get("/v1/runs/run_1/policy-decisions")

    assert response.json() == {"decisions": []}


def test_list_policy_decisions__404_for_unknown_run(client: TestClient) -> None:
    response = client.get("/v1/runs/run_missing/policy-decisions")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


async def test_get_replay_bundle__manifest_then_events_in_seq_order(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    await trace_store.upsert_run(_run(status="ok", totals={"events": 3}))
    await trace_store.upsert_events(
        [_event(seq=1, kind="step.started"), _event(seq=0, kind="run.started")]
    )

    response = client.get("/v1/runs/run_1/replay-bundle")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/x-ndjson"
    lines = response.text.strip("\n").split("\n")
    manifest = json.loads(lines[0])
    assert manifest["schema"] == "trazo.replay-bundle.v1"
    assert manifest["run_id"] == "run_1"
    assert manifest["event_count"] == 2
    assert manifest["totals"] == {"events": 3}

    events = [json.loads(line) for line in lines[1:]]
    assert [e["seq"] for e in events] == [0, 1]
    assert [e["kind"] for e in events] == ["run.started", "step.started"]


async def test_get_replay_bundle__dedupes_blob_manifest_across_events(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    await trace_store.upsert_run(_run())
    await trace_store.upsert_events(
        [
            _event(
                seq=0,
                blobs=[
                    {
                        "field": "payload.entry_input",
                        "sha256": "sha256:aaa",
                        "bytes": 10,
                    }
                ],
            ),
            _event(
                seq=1,
                blobs=[
                    {
                        "field": "payload.entry_input",
                        "sha256": "sha256:aaa",
                        "bytes": 10,
                    }
                ],
            ),
            _event(
                seq=2,
                blobs=[
                    {"field": "payload.result", "sha256": "sha256:bbb", "bytes": 20}
                ],
            ),
        ]
    )

    response = client.get("/v1/runs/run_1/replay-bundle")

    manifest = json.loads(response.text.split("\n", 1)[0])
    assert manifest["blob_manifest"] == [
        {"sha256": "sha256:aaa", "bytes": 10},
        {"sha256": "sha256:bbb", "bytes": 20},
    ]


def test_get_replay_bundle__404_for_unknown_run(client: TestClient) -> None:
    response = client.get("/v1/runs/run_does_not_exist/replay-bundle")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


async def test_get_replay_bundle__immutable_cache_once_finished(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    await trace_store.upsert_run(_run(status="ok"))

    response = client.get("/v1/runs/run_1/replay-bundle")

    assert "immutable" in response.headers["cache-control"]
    assert "etag" in response.headers


async def test_get_replay_bundle__not_cached_while_still_running(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    await trace_store.upsert_run(_run(status="running"))

    response = client.get("/v1/runs/run_1/replay-bundle")

    assert response.headers["cache-control"] == "no-store"


async def test_get_replay_bundle__byte_stable_across_repeated_fetches(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    """P4-01's DoD: bundle round-trips a sample corpus byte-stable."""
    await trace_store.upsert_run(_run(status="ok"))
    await trace_store.upsert_events([_event(seq=0), _event(seq=1), _event(seq=2)])

    first = client.get("/v1/runs/run_1/replay-bundle")
    second = client.get("/v1/runs/run_1/replay-bundle")

    assert first.content == second.content
    assert first.headers["etag"] == second.headers["etag"]


def test_get_blob__returns_stored_bytes_with_cache_headers(client: TestClient) -> None:
    import hashlib

    data = b'{"hello":"world"}'
    digest = hashlib.sha256(data).hexdigest()
    blob_root = client.app.state.blob_store._root  # type: ignore[attr-defined]
    shard = blob_root / digest[:2] / digest[2:4]
    shard.mkdir(parents=True, exist_ok=True)
    (shard / digest).write_bytes(data)

    response = client.get(f"/v1/blobs/sha256:{digest}")

    assert response.status_code == 200
    assert response.content == data
    assert response.headers["content-type"] == "application/json"
    assert "immutable" in response.headers["cache-control"]


def test_get_blob__404_for_unknown_sha(client: TestClient) -> None:
    response = client.get("/v1/blobs/sha256:" + "0" * 64)

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


async def test_get_stats__aggregates_counts_cost_and_daily_series(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    """The Overview's every number comes from here in one round trip
    (ARCHITECTURE.md §2.3: the dashboard computes no rollups itself)."""
    await trace_store.upsert_run(
        _run(run_id="run_ok", status="ok", totals={"cost_usd": 1.5})
    )
    await trace_store.upsert_run(
        _run(
            run_id="run_err",
            status="error",
            started_at=_NOW + timedelta(days=1),
            totals={"cost_usd": 2.25},
        )
    )
    await trace_store.upsert_run(
        _run(run_id="run_live", status="running", project_id="proj_2", totals={})
    )

    body = client.get("/v1/stats").json()

    assert body["total_runs"] == 3
    assert body["failed_runs"] == 1
    assert body["active_runs"] == 1
    assert body["total_cost_usd"] == 3.75
    assert body["window_runs"] == 3
    # one bucket per distinct UTC day, oldest first
    assert [p["date"] for p in body["daily"]] == [
        _NOW.date().isoformat(),
        (_NOW + timedelta(days=1)).date().isoformat(),
    ]
    assert body["daily"][1]["failed_runs"] == 1
    # cost split by project, biggest spender first
    assert body["cost_by_project"][0]["project_id"] == "proj_1"
    assert body["cost_by_project"][0]["cost_usd"] == 3.75


async def test_get_stats__counts_denials_and_lists_detections_across_runs(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    """Both feeds are fleet-wide, not per-run: an operator's incident
    view asks "what is going wrong right now", across every run."""
    await trace_store.upsert_run(_run(run_id="run_a"))
    await trace_store.upsert_run(_run(run_id="run_b"))
    await trace_store.insert_detection(
        _detection(detection_id="det_a", run_id="run_a", raised_at=_NOW)
    )
    await trace_store.insert_detection(
        _detection(
            detection_id="det_b",
            run_id="run_b",
            detector="budget",
            raised_at=_NOW + timedelta(minutes=5),
        )
    )
    await trace_store.insert_policy_decision(
        _policy_decision(decision_id="dec_deny", run_id="run_a", decision="deny")
    )
    await trace_store.insert_policy_decision(
        _policy_decision(decision_id="dec_allow", run_id="run_b", decision="allow")
    )

    body = client.get("/v1/stats").json()

    assert body["policy_denials"] == 1  # the allow is not a violation
    assert [d["detection_id"] for d in body["recent_detections"]] == [
        "det_b",
        "det_a",
    ]


def test_get_stats__empty_store_reports_zeros_not_an_error(
    client: TestClient,
) -> None:
    body = client.get("/v1/stats").json()

    assert body["total_runs"] == 0
    assert body["total_cost_usd"] == 0.0
    assert body["daily"] == []
    assert body["recent_detections"] == []


async def test_get_stats__days_window_excludes_older_runs_and_computes_deltas(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    """`days` bounds the window AND defines the baseline: the delta is
    against the equally-long window immediately before it."""
    now = datetime.now(timezone.utc)
    # 2 runs inside the last 7 days ...
    await trace_store.upsert_run(
        _run(run_id="recent_a", started_at=now - timedelta(days=1))
    )
    await trace_store.upsert_run(
        _run(run_id="recent_b", started_at=now - timedelta(days=2))
    )
    # ... 1 run in the preceding 7-day window (the baseline) ...
    await trace_store.upsert_run(
        _run(run_id="prior", started_at=now - timedelta(days=9))
    )
    # ... and 1 far outside both, which must not count anywhere.
    await trace_store.upsert_run(
        _run(run_id="ancient", started_at=now - timedelta(days=90))
    )

    body = client.get("/v1/stats", params={"days": 7}).json()

    assert body["total_runs"] == 2
    assert body["range_days"] == 7
    # 2 this window vs 1 the window before = +100%
    assert body["deltas"]["runs_pct"] == 100.0


def test_get_stats__delta_is_null_when_there_is_no_prior_window(
    client: TestClient,
) -> None:
    """An empty baseline yields null, not a misleading +100%."""
    body = client.get("/v1/stats", params={"days": 7}).json()

    assert body["deltas"]["runs_pct"] is None
    assert body["deltas"]["cost_pct"] is None


async def test_get_stats__project_filter_scopes_every_counter(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    await trace_store.upsert_run(
        _run(run_id="a", project_id="proj_1", totals={"cost_usd": 2.0})
    )
    await trace_store.upsert_run(
        _run(run_id="b", project_id="proj_2", totals={"cost_usd": 5.0})
    )

    body = client.get("/v1/stats", params={"project": "proj_1"}).json()

    assert body["total_runs"] == 1
    assert body["total_cost_usd"] == 2.0


async def test_list_recent_events__newest_first_across_runs_and_filters_by_kind(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    await trace_store.upsert_events(
        [
            _event(seq=0, kind="run.started", ts=_NOW),
            _event(seq=1, kind="tool.call", ts=_NOW + timedelta(minutes=1)),
        ]
    )

    body = client.get("/v1/events/recent").json()
    assert [e["kind"] for e in body["events"]] == ["tool.call", "run.started"]

    filtered = client.get("/v1/events/recent", params={"kind": "tool.call"}).json()
    assert [e["kind"] for e in filtered["events"]] == ["tool.call"]


async def test_list_recent_events__breaks_ts_ties_by_event_id(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    """A fast agent emits many events inside one millisecond, so ordering
    on ts alone left the Traces feed showing a single run's events
    shuffled. event_id is a ULID — monotonic within a run — so it is the
    correct tiebreaker.
    """
    await trace_store.upsert_events(
        [
            _event(seq=n, event_id=f"evt_{n:02d}", kind="step.started", ts=_NOW)
            for n in range(5)
        ]
    )

    body = client.get("/v1/events/recent").json()

    assert [e["seq"] for e in body["events"]] == [4, 3, 2, 1, 0]


async def test_list_tools__rolls_up_calls_errors_and_mean_latency(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    def tool_event(seq: int, name: str, status: str, latency: float) -> EventRow:
        return _event(
            seq=seq,
            kind="tool.call",
            payload={
                "tool_name": name,
                "args": {},
                "result": "",
                "status": status,
                "latency_ms": latency,
                "side_effect_class": "external",
            },
        )

    await trace_store.upsert_events(
        [
            tool_event(0, "web_search", "ok", 10.0),
            tool_event(1, "web_search", "error", 20.0),
            tool_event(2, "fetch_doc", "ok", 5.0),
        ]
    )

    body = client.get("/v1/tools").json()

    # busiest tool first
    assert [t["tool_name"] for t in body["tools"]] == ["web_search", "fetch_doc"]
    web_search = body["tools"][0]
    assert web_search["calls"] == 2
    assert web_search["errors"] == 1
    assert web_search["avg_latency_ms"] == 15.0
    assert web_search["side_effect_class"] == "external"


async def test_list_agents__reports_unattributed_events_rather_than_hiding_them(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    """The LangGraph adapter leaves agent_id null, so "no agents" must be
    distinguishable from "nothing ran"."""
    await trace_store.upsert_events(
        [
            _event(seq=0, kind="run.started"),
            _event(seq=1, kind="llm.call", agent_id="researcher"),
        ]
    )

    body = client.get("/v1/agents").json()

    assert [a["agent_id"] for a in body["agents"]] == ["researcher"]
    assert body["agents"][0]["events"] == 1
    assert body["agents"][0]["runs"] == 1
    assert body["unattributed_events"] == 1


async def test_list_projects__counts_runs_per_project_busiest_first(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    await trace_store.upsert_run(_run(run_id="a", project_id="proj_busy"))
    await trace_store.upsert_run(_run(run_id="b", project_id="proj_busy"))
    await trace_store.upsert_run(_run(run_id="c", project_id="proj_quiet"))

    body = client.get("/v1/projects").json()

    assert [p["project_id"] for p in body["projects"]] == ["proj_busy", "proj_quiet"]
    assert body["projects"][0]["runs"] == 2
