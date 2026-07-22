"""Unit tests for InMemoryTraceStore — proves TRZ-P1-04's upsert DoD:
upsert on (run_id, seq) is idempotent, and run rollups update in place.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trazo_server.store.memory_trace_store import InMemoryTraceStore
from trazo_server.store.rows import EventRow, RunRow

_NOW = datetime(2026, 7, 18, 9, 30, tzinfo=timezone.utc)


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


async def test_trace_store__upsert_run_then_get_round_trips() -> None:
    store = InMemoryTraceStore()
    await store.upsert_run(_run())

    fetched = await store.get_run("run_1")

    assert fetched is not None
    assert fetched.status == "running"


async def test_trace_store__upsert_run_twice_updates_rollup_in_place() -> None:
    store = InMemoryTraceStore()
    await store.upsert_run(_run(status="running"))

    await store.upsert_run(
        _run(status="ok", finished_at=_NOW, totals={"events": 9, "llm_calls": 1})
    )

    fetched = await store.get_run("run_1")
    assert fetched is not None
    assert fetched.status == "ok"
    assert fetched.totals == {"events": 9, "llm_calls": 1}


async def test_trace_store__rollup_update_does_not_overwrite_creation_fields() -> None:
    """A rollup-only caller (e.g. run.finished, which doesn't know the
    original tags) must not be able to wipe them by passing a different
    value — only status/finished_at/totals are mutable post-creation."""
    store = InMemoryTraceStore()
    await store.upsert_run(_run(tags={"env": "demo"}, framework="langgraph"))

    await store.upsert_run(
        _run(status="ok", tags={}, framework="placeholder-should-be-ignored")
    )

    fetched = await store.get_run("run_1")
    assert fetched is not None
    assert fetched.tags == {"env": "demo"}
    assert fetched.framework == "langgraph"


async def test_trace_store__upsert_events_is_idempotent_on_run_id_and_seq() -> None:
    """Re-sending the same (run_id, seq) batch must not create duplicates —
    the exact behavior the events table's PRIMARY KEY (run_id, seq) buys us
    in Postgres via ON CONFLICT DO UPDATE."""
    store = InMemoryTraceStore()
    batch = [_event(seq=0), _event(seq=1, kind="llm.call")]

    await store.upsert_events(batch)
    await store.upsert_events(batch)  # re-send: simulates an ingest retry

    events = await store.get_events("run_1")
    assert [e.seq for e in events] == [0, 1]


async def test_trace_store__upsert_events_overwrites_same_seq_with_new_content() -> (
    None
):
    store = InMemoryTraceStore()
    await store.upsert_events([_event(seq=0, kind="run.started")])

    await store.upsert_events([_event(seq=0, kind="run.started", agent_id="fixed")])

    [event] = await store.get_events("run_1")
    assert event.agent_id == "fixed"


async def test_trace_store__get_events_orders_by_seq_and_respects_filters() -> None:
    store = InMemoryTraceStore()
    await store.upsert_events(
        [
            _event(seq=2, kind="llm.call"),
            _event(seq=0, kind="run.started"),
            _event(seq=1, kind="step.started"),
        ]
    )

    ordered = await store.get_events("run_1")
    assert [e.seq for e in ordered] == [0, 1, 2]

    after = await store.get_events("run_1", after_seq=0)
    assert [e.seq for e in after] == [1, 2]

    by_kind = await store.get_events("run_1", kind="llm.call")
    assert [e.seq for e in by_kind] == [2]


async def test_trace_store__list_runs_filters_by_project_and_status() -> None:
    store = InMemoryTraceStore()
    await store.upsert_run(_run(run_id="run_a", project_id="proj_a", status="ok"))
    await store.upsert_run(_run(run_id="run_b", project_id="proj_a", status="running"))
    await store.upsert_run(_run(run_id="run_c", project_id="proj_b", status="ok"))

    proj_a_runs = await store.list_runs(project_id="proj_a")
    assert {r.run_id for r in proj_a_runs} == {"run_a", "run_b"}

    ok_runs = await store.list_runs(status="ok")
    assert {r.run_id for r in ok_runs} == {"run_a", "run_c"}


async def test_trace_store__list_runs_keyset_pagination_stable_under_insert() -> None:
    """TRZ-P1-07 DoD: a page fetched via ``before`` must be unaffected by a
    run inserted after the cursor was issued — the classic OFFSET failure
    mode (new row shifts everything, causing a skip or a duplicate) must
    not happen with keyset pagination."""
    store = InMemoryTraceStore()
    base = _NOW
    for i in range(1, 5):  # run_1..run_4, ascending start time
        await store.upsert_run(
            _run(run_id=f"run_{i}", started_at=base + timedelta(minutes=i))
        )

    page1 = await store.list_runs(limit=2)
    assert [r.run_id for r in page1] == ["run_4", "run_3"]
    cursor = (page1[-1].started_at, page1[-1].run_id)

    # Concurrent insert: a brand-new run, newer than everything seen so far.
    await store.upsert_run(_run(run_id="run_5", started_at=base + timedelta(minutes=5)))

    page2 = await store.list_runs(limit=2, before=cursor)
    assert [r.run_id for r in page2] == ["run_2", "run_1"]


async def test_trace_store__get_project_events_spans_runs_ordered_by_event_id() -> None:
    store = InMemoryTraceStore()
    await store.upsert_run(_run(run_id="run_a", project_id="proj_a"))
    await store.upsert_run(_run(run_id="run_b", project_id="proj_a"))
    await store.upsert_run(_run(run_id="run_other", project_id="proj_b"))
    await store.upsert_events(
        [
            _event(run_id="run_a", seq=0, event_id="evt_0000000000000000000000001"),
            _event(run_id="run_b", seq=0, event_id="evt_0000000000000000000000002"),
            _event(run_id="run_other", seq=0, event_id="evt_0000000000000000000000003"),
        ]
    )

    events = await store.get_project_events("proj_a")

    assert [e.event_id for e in events] == [
        "evt_0000000000000000000000001",
        "evt_0000000000000000000000002",
    ]


async def test_trace_store__get_project_events_after_event_id_resumes_correctly() -> (
    None
):
    store = InMemoryTraceStore()
    await store.upsert_run(_run(run_id="run_a", project_id="proj_a"))
    await store.upsert_events(
        [
            _event(run_id="run_a", seq=0, event_id="evt_0000000000000000000000001"),
            _event(run_id="run_a", seq=1, event_id="evt_0000000000000000000000002"),
            _event(run_id="run_a", seq=2, event_id="evt_0000000000000000000000003"),
        ]
    )

    events = await store.get_project_events(
        "proj_a", after_event_id="evt_0000000000000000000000001"
    )

    assert [e.event_id for e in events] == [
        "evt_0000000000000000000000002",
        "evt_0000000000000000000000003",
    ]
