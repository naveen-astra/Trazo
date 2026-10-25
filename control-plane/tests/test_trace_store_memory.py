"""Unit tests for InMemoryTraceStore — proves TRZ-P1-04's upsert DoD:
upsert on (run_id, seq) is idempotent, and run rollups update in place.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trazo_server.store.memory_trace_store import InMemoryTraceStore
from trazo_server.store.rows import (
    AppendedEvent,
    DetectionRow,
    EventRow,
    PolicyDecisionRow,
    ReplayReportRow,
    RunRow,
)

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


async def test_trace_store__get_project_events_spans_runs_in_storage_order() -> None:
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


async def test_trace_store__get_project_events_resumes_after_an_ingest_seq() -> None:
    store = InMemoryTraceStore()
    await store.upsert_run(_run(run_id="run_a", project_id="proj_a"))
    await store.upsert_events(
        [
            _event(run_id="run_a", seq=0, event_id="evt_0000000000000000000000001"),
            _event(run_id="run_a", seq=1, event_id="evt_0000000000000000000000002"),
            _event(run_id="run_a", seq=2, event_id="evt_0000000000000000000000003"),
        ]
    )

    first = (await store.get_project_events("proj_a"))[0].ingest_seq
    events = await store.get_project_events("proj_a", after_ingest_seq=first)

    assert [e.event_id for e in events] == [
        "evt_0000000000000000000000002",
        "evt_0000000000000000000000003",
    ]


async def _server_event(
    store: InMemoryTraceStore,
    *,
    after_seq: int | None,
    event_id: str,
    run_id: str = "run_1",
    idempotency_key: str | None = None,
) -> AppendedEvent:
    return await store.append_server_event(
        run_id=run_id,
        project="research-assistant",
        after_seq=after_seq,
        event_id=event_id,
        kind="detection.raised",
        ts=_NOW,
        payload={"detector": "loop"},
        idempotency_key=idempotency_key,
    )


async def test_trace_store__server_event_attaches_after_the_given_sdk_event() -> None:
    store = InMemoryTraceStore()
    await store.upsert_events(
        [
            _event(seq=0, event_id="evt_0"),
            _event(seq=1, event_id="evt_1", kind="llm.call"),
            _event(seq=2, event_id="evt_2", kind="llm.call"),
        ]
    )

    appended = await _server_event(store, after_seq=1, event_id="evt_det")

    assert (appended.seq, appended.sub_seq, appended.created) == (1, 1, True)
    order = [(e.seq, e.sub_seq, e.event_id) for e in await store.get_events("run_1")]
    assert order == [
        (0, 0, "evt_0"),
        (1, 0, "evt_1"),
        (1, 1, "evt_det"),
        (2, 0, "evt_2"),
    ]


async def test_trace_store__server_event_never_takes_an_sdk_slot() -> None:
    """Regression: the SDK numbers its events in the agent's process; a
    server event that took `max + 1` collided with one still in flight."""
    store = InMemoryTraceStore()
    await store.upsert_events([_event(seq=0, event_id="evt_0")])
    await _server_event(store, after_seq=None, event_id="evt_det")

    await store.upsert_events([_event(seq=1, event_id="evt_1", kind="llm.call")])

    ids = {e.event_id for e in await store.get_events("run_1")}
    assert ids == {"evt_0", "evt_1", "evt_det"}


async def test_trace_store__server_event_defaults_to_the_latest_sdk_event() -> None:
    store = InMemoryTraceStore()
    await store.upsert_events(
        [_event(seq=0, event_id="evt_0"), _event(seq=4, event_id="evt_4")]
    )

    appended = await _server_event(store, after_seq=None, event_id="evt_det")

    assert (appended.seq, appended.sub_seq) == (4, 1)


async def test_trace_store__server_events_under_one_seq_take_successive_slots() -> None:
    store = InMemoryTraceStore()
    first = await _server_event(store, after_seq=3, event_id="evt_a")
    second = await _server_event(store, after_seq=3, event_id="evt_b")

    assert (first.sub_seq, second.sub_seq) == (1, 2)


async def test_trace_store__server_event_for_an_unseen_run_creates_a_placeholder() -> (
    None
):
    store = InMemoryTraceStore()

    appended = await _server_event(
        store, after_seq=None, event_id="evt_det", run_id="run_new"
    )

    assert (appended.seq, appended.sub_seq) == (0, 1)
    run = await store.get_run("run_new")
    assert run is not None and run.framework == "unknown"


async def test_trace_store__server_event_is_idempotent_on_its_key() -> None:
    store = InMemoryTraceStore()
    first = await _server_event(
        store, after_seq=0, event_id="evt_a", idempotency_key="k"
    )
    again = await _server_event(
        store, after_seq=0, event_id="evt_b", idempotency_key="k"
    )

    assert first.created and not again.created
    assert again.event_id == "evt_a"
    assert len(await store.get_server_events("run_1")) == 1


async def test_trace_store__position_cursor_does_not_skip_a_shared_seq() -> None:
    store = InMemoryTraceStore()
    await store.upsert_events(
        [_event(seq=0, event_id="evt_0"), _event(seq=1, event_id="evt_1")]
    )
    await _server_event(store, after_seq=0, event_id="evt_det")

    page_one = await store.get_events("run_1", limit=1)
    rest = await store.get_events(
        "run_1",
        after_seq=page_one[-1].seq,
        after_sub_seq=page_one[-1].sub_seq,
        limit=10,
    )

    assert [e.event_id for e in page_one + rest] == ["evt_0", "evt_det", "evt_1"]


async def test_trace_store__insert_detection_then_list_round_trips() -> None:
    store = InMemoryTraceStore()
    detection = DetectionRow(
        detection_id="det_1",
        run_id="run_1",
        detector="loop",
        severity="warn",
        raised_at=_NOW,
        evidence=[{"run_id": "run_1", "seq": 5}],
        details={"repeat_count": 4},
    )

    await store.insert_detection(detection)

    [fetched] = await store.list_detections("run_1")
    assert fetched == detection


async def test_trace_store__insert_detection_is_idempotent_on_detection_id() -> None:
    store = InMemoryTraceStore()
    detection = DetectionRow(
        detection_id="det_1",
        run_id="run_1",
        detector="loop",
        severity="warn",
        raised_at=_NOW,
        evidence=[],
        details={},
    )

    await store.insert_detection(detection)
    await store.insert_detection(detection)  # simulates a bus redelivery

    assert len(await store.list_detections("run_1")) == 1


async def test_trace_store__list_detections_orders_most_recent_first() -> None:
    store = InMemoryTraceStore()
    older = DetectionRow(
        detection_id="det_older",
        run_id="run_1",
        detector="loop",
        severity="warn",
        raised_at=_NOW,
        evidence=[],
        details={},
    )
    newer = DetectionRow(
        detection_id="det_newer",
        run_id="run_1",
        detector="budget",
        severity="critical",
        raised_at=_NOW + timedelta(minutes=1),
        evidence=[],
        details={},
    )

    await store.insert_detection(older)
    await store.insert_detection(newer)

    fetched = await store.list_detections("run_1")
    assert [d.detection_id for d in fetched] == ["det_newer", "det_older"]


def _policy_decision(**overrides: object) -> PolicyDecisionRow:
    defaults: dict[str, object] = {
        "decision_id": "dec_1",
        "run_id": "run_1",
        "policy_id": "cost_cap",
        "action_kind": "tool.call",
        "action_fp": f"sha256:{'a' * 64}",
        "decision": "deny",
        "mode": "enforce",
        "reasons": ["over cap"],
        "decided_at": _NOW,
        "eval_ms": 12.5,
    }
    defaults.update(overrides)
    return PolicyDecisionRow(**defaults)  # type: ignore[arg-type]


async def test_trace_store__insert_policy_decision_then_list_round_trips() -> None:
    store = InMemoryTraceStore()
    decision = _policy_decision()

    await store.insert_policy_decision(decision)

    [fetched] = await store.list_policy_decisions("run_1")
    assert fetched == decision


async def test_trace_store__insert_policy_decision_is_idempotent_on_decision_id() -> (
    None
):
    store = InMemoryTraceStore()
    decision = _policy_decision()

    await store.insert_policy_decision(decision)
    await store.insert_policy_decision(decision)  # simulates a bus redelivery

    assert len(await store.list_policy_decisions("run_1")) == 1


async def test_trace_store__list_policy_decisions_orders_most_recent_first() -> None:
    store = InMemoryTraceStore()
    older = _policy_decision(decision_id="dec_older", decided_at=_NOW)
    newer = _policy_decision(
        decision_id="dec_newer", decided_at=_NOW + timedelta(minutes=1)
    )

    await store.insert_policy_decision(older)
    await store.insert_policy_decision(newer)

    fetched = await store.list_policy_decisions("run_1")
    assert [d.decision_id for d in fetched] == ["dec_newer", "dec_older"]


def _replay_report(**overrides: object) -> ReplayReportRow:
    defaults: dict[str, object] = {
        "run_id": "run_1",
        "boundary_fidelity": 1.0,
        "state_fidelity": 1.0,
        "matched": 2,
        "reordered": 0,
        "divergences": [],
        "replay_overhead": 0.4,
        "verified_at": _NOW,
    }
    defaults.update(overrides)
    return ReplayReportRow(**defaults)  # type: ignore[arg-type]


async def test_trace_store__get_replay_report_is_none_before_any_verify() -> None:
    store = InMemoryTraceStore()

    assert await store.get_replay_report("run_1") is None


async def test_trace_store__upsert_replay_report_then_get_round_trips() -> None:
    store = InMemoryTraceStore()
    report = _replay_report()

    await store.upsert_replay_report(report)

    assert await store.get_replay_report("run_1") == report


async def test_trace_store__upsert_replay_report_replaces_not_accumulates() -> None:
    """A re-verify overwrites the previous report for the same run —
    only the latest result against the current code is meaningful."""
    store = InMemoryTraceStore()
    await store.upsert_replay_report(
        _replay_report(boundary_fidelity=0.5, matched=1, divergences=[{"kind": "x"}])
    )

    await store.upsert_replay_report(
        _replay_report(boundary_fidelity=1.0, matched=2, divergences=[])
    )

    fetched = await store.get_replay_report("run_1")
    assert fetched is not None
    assert fetched.boundary_fidelity == 1.0
    assert fetched.divergences == []


async def test_trace_store__get_project_events_orders_by_storage_not_event_id() -> None:
    """An event_id carries its minting machine's clock; storage order is
    what the firehose needs."""
    store = InMemoryTraceStore()
    await store.upsert_run(_run(run_id="run_a", project_id="proj_a"))
    await store.upsert_events([_event(run_id="run_a", seq=0, event_id="evt_9")])
    await store.upsert_events([_event(run_id="run_a", seq=1, event_id="evt_1")])

    events = await store.get_project_events("proj_a")

    assert [e.event_id for e in events] == ["evt_9", "evt_1"]


async def test_trace_store__get_project_events_honours_exclusions() -> None:
    store = InMemoryTraceStore()
    await store.upsert_run(_run(run_id="run_a", project_id="proj_a"))
    await store.upsert_events(
        [_event(run_id="run_a", seq=i, event_id=f"evt_{i}") for i in range(3)]
    )
    second = (await store.get_project_events("proj_a"))[1].ingest_seq

    events = await store.get_project_events(
        "proj_a", exclude_ingest_seqs=frozenset({second})
    )

    assert [e.event_id for e in events] == ["evt_0", "evt_2"]


async def test_trace_store__an_upsert_keeps_the_rows_ingest_seq() -> None:
    """Mirrors Postgres: a redelivered event updates its row in place and
    must not jump to the head of the firehose."""
    store = InMemoryTraceStore()
    await store.upsert_events([_event(seq=0, event_id="evt_0")])
    await store.upsert_events([_event(seq=1, event_id="evt_1")])
    before = {e.event_id: e.ingest_seq for e in await store.get_events("run_1")}

    await store.upsert_events([_event(seq=0, event_id="evt_0")])

    after = {e.event_id: e.ingest_seq for e in await store.get_events("run_1")}
    assert after == before
