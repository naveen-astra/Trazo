"""Tests for the live SSE API (TRZ-P2-06).

Unit tests exercise ``stream_run_events``/``stream_project_events``
directly against InMemoryTraceStore with a fake ``is_disconnected``
callable — this is what makes the firehose (which never terminates on
its own) testable without a real, hanging HTTP connection. One HTTP-level
test proves the actual endpoint wiring (headers, media type, Last-Event-ID
resume) using a run that reaches ``run.finished`` immediately, so the
StreamingResponse completes fast under TestClient.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from trazo_server.api import live as live_module
from trazo_server.api.deps import get_trace_store
from trazo_server.api.live import (
    parse_resume_position,
    stream_project_events,
    stream_run_events,
)
from trazo_server.api.projects import resolve_project_id
from trazo_server.app import create_app
from trazo_server.config import Settings
from trazo_server.store.memory_trace_store import InMemoryTraceStore
from trazo_server.store.rows import EventRow, RunRow

_NOW = datetime(2026, 7, 18, 9, 30, tzinfo=timezone.utc)


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


async def _never_disconnected() -> bool:
    return False


class _DisconnectAfterN:
    def __init__(self, n: int) -> None:
        self._n = n
        self._calls = 0

    async def __call__(self) -> bool:
        self._calls += 1
        return self._calls > self._n


async def _collect(gen: Any, *, timeout: float = 5.0) -> list[str]:
    async def _run() -> list[str]:
        return [chunk async for chunk in gen]

    return await asyncio.wait_for(_run(), timeout=timeout)


async def test_stream_run_events__yields_events_in_order_stops_at_finished() -> None:
    store = InMemoryTraceStore()
    await store.upsert_events(
        [
            _event(seq=0, event_id="evt_0", kind="run.started"),
            _event(seq=1, event_id="evt_1", kind="step.started"),
            _event(seq=2, event_id="evt_2", kind="run.finished"),
        ]
    )

    chunks = await _collect(
        stream_run_events(
            store,
            "run_1",
            after=None,
            is_disconnected=_never_disconnected,
            late_event_grace=0,
        )
    )

    assert len(chunks) == 3
    assert chunks[0].startswith("id: 0.0\ndata: ")
    assert '"kind":"run.started"' in chunks[0]
    assert chunks[2].startswith("id: 2.0\ndata: ")
    assert '"kind":"run.finished"' in chunks[2]


async def test_stream_run_events__resumes_from_last_event_id() -> None:
    store = InMemoryTraceStore()
    await store.upsert_events(
        [
            _event(seq=0, event_id="evt_0", kind="run.started"),
            _event(seq=1, event_id="evt_1", kind="step.started"),
            _event(seq=2, event_id="evt_2", kind="run.finished"),
        ]
    )

    chunks = await _collect(
        stream_run_events(
            store,
            "run_1",
            after=(0, 0),
            is_disconnected=_never_disconnected,
            late_event_grace=0,
        )
    )

    assert len(chunks) == 2
    assert "step.started" in chunks[0]
    assert "run.finished" in chunks[1]


async def test_stream_run_events__stops_when_client_disconnects() -> None:
    store = InMemoryTraceStore()  # no events at all; run never "finishes"

    chunks = await _collect(
        stream_run_events(
            store,
            "run_1",
            after=None,
            is_disconnected=_DisconnectAfterN(2),
            poll_interval=0.01,
        )
    )

    assert chunks == []


async def _detection(
    store: InMemoryTraceStore, *, after_seq: int, event_id: str
) -> None:
    await store.append_server_event(
        run_id="run_1",
        project="research-assistant",
        after_seq=after_seq,
        event_id=event_id,
        kind="detection.raised",
        ts=_NOW,
        payload={"detector": "loop"},
    )


async def test_stream_run_events__sends_a_server_event_written_behind_the_cursor() -> (
    None
):
    """A detection attaches right after the event that caused it, but is
    written later -- after the stream has already moved past that point. A
    cursor alone never goes back for it."""
    store = InMemoryTraceStore()
    await store.upsert_events(
        [
            _event(seq=0, event_id="evt_0", kind="run.started"),
            _event(seq=1, event_id="evt_1", kind="tool.call"),
            _event(seq=2, event_id="evt_2", kind="step.started"),
        ]
    )
    stream = stream_run_events(
        store,
        "run_1",
        after=None,
        is_disconnected=_never_disconnected,
        poll_interval=0.01,
        late_event_grace=0,
    )
    first_three = [await anext(stream) for _ in range(3)]
    assert "step.started" in first_three[2]

    # The detector, reacting to seq 1, records its detection now.
    await _detection(store, after_seq=1, event_id="evt_det")
    await store.upsert_events([_event(seq=3, event_id="evt_3", kind="run.finished")])

    rest = await _collect(stream)

    detection_chunks = [c for c in rest if "detection.raised" in c]
    assert len(detection_chunks) == 1
    # Its SSE id is the stream's cursor, not the detection's own (earlier)
    # position, so a reconnect does not rewind.
    assert detection_chunks[0].startswith("id: 2.0\n")
    assert any("run.finished" in c for c in rest)


async def test_stream_run_events__waits_for_a_detection_raised_after_the_run_ends() -> (
    None
):
    store = InMemoryTraceStore()
    await store.upsert_events(
        [
            _event(seq=0, event_id="evt_0", kind="run.started"),
            _event(seq=1, event_id="evt_1", kind="run.finished"),
        ]
    )
    stream = stream_run_events(
        store,
        "run_1",
        after=None,
        is_disconnected=_never_disconnected,
        poll_interval=0.01,
        late_event_grace=2.0,
    )
    assert "run.started" in await anext(stream)
    assert "run.finished" in await anext(stream)

    await _detection(store, after_seq=0, event_id="evt_late")

    late = await asyncio.wait_for(anext(stream), timeout=2.0)
    assert "evt_late" in late


async def test_stream_run_events__sends_each_server_event_once() -> None:
    store = InMemoryTraceStore()
    await store.upsert_events([_event(seq=0, event_id="evt_0", kind="run.started")])
    await _detection(store, after_seq=0, event_id="evt_det")
    await store.upsert_events([_event(seq=1, event_id="evt_1", kind="run.finished")])

    chunks = await _collect(
        stream_run_events(
            store,
            "run_1",
            after=None,
            is_disconnected=_never_disconnected,
            poll_interval=0.01,
            late_event_grace=0.05,
        )
    )

    assert sum("evt_det" in chunk for chunk in chunks) == 1
    kinds = [
        k
        for c in chunks
        for k in ("run.started", "detection", "run.finished")
        if k in c
    ]
    assert kinds == ["run.started", "detection", "run.finished"]


async def test_stream_run_events__resume_skips_server_events_already_sent() -> None:
    store = InMemoryTraceStore()
    await store.upsert_events([_event(seq=0, event_id="evt_0", kind="run.started")])
    await _detection(store, after_seq=0, event_id="evt_det")
    await store.upsert_events([_event(seq=1, event_id="evt_1", kind="run.finished")])

    chunks = await _collect(
        stream_run_events(
            store,
            "run_1",
            after=(0, 1),  # resuming just after the detection
            is_disconnected=_never_disconnected,
            late_event_grace=0,
        )
    )

    assert [("evt_det" in c, "run.finished" in c) for c in chunks] == [(False, True)]


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, None),
        ("", None),
        ("7", (7, None)),
        ("7.2", (7, 2)),
        ("garbage", None),
    ],
)
def test_parse_resume_position(header: str | None, expected: object) -> None:
    assert parse_resume_position(header) == expected


async def test_stream_project_events__spans_runs_ordered_by_event_id() -> None:
    store = InMemoryTraceStore()
    await store.upsert_run(_run(run_id="run_a", project_id="proj_a"))
    await store.upsert_run(_run(run_id="run_b", project_id="proj_a"))
    await store.upsert_events(
        [
            _event(run_id="run_a", seq=0, event_id="evt_001"),
            _event(run_id="run_b", seq=0, event_id="evt_002"),
        ]
    )

    chunks = await _collect(
        stream_project_events(
            store,
            "proj_a",
            after_event_id=None,
            is_disconnected=_DisconnectAfterN(1),
            poll_interval=0.01,
        )
    )

    assert len(chunks) == 2
    assert chunks[0].startswith("id: evt_001")
    assert chunks[1].startswith("id: evt_002")


async def test_stream_project_events__tail_skips_the_backlog() -> None:
    """A tail subscriber gets nothing for events that predate it.

    This is what keeps the dashboard's refresh trigger cheap: it only
    needs to know *that* something happened, so replaying the whole
    history first would cost more the longer the deployment has run.
    """
    store = InMemoryTraceStore()
    await store.upsert_run(_run(run_id="run_a", project_id="proj_a"))
    await store.upsert_events(
        [
            _event(run_id="run_a", seq=0, event_id="evt_001"),
            _event(run_id="run_a", seq=1, event_id="evt_002"),
        ]
    )

    chunks = await _collect(
        stream_project_events(
            store,
            "proj_a",
            after_event_id=None,
            is_disconnected=_DisconnectAfterN(1),
            tail=True,
            poll_interval=0.01,
        )
    )

    assert chunks == []


async def test_stream_project_events__tail_still_yields_events_that_arrive_after() -> (
    None
):
    store = InMemoryTraceStore()
    await store.upsert_run(_run(run_id="run_a", project_id="proj_a"))
    await store.upsert_events([_event(run_id="run_a", seq=0, event_id="evt_001")])

    stream = stream_project_events(
        store,
        "proj_a",
        after_event_id=None,
        is_disconnected=_never_disconnected,
        tail=True,
        poll_interval=0.01,
    )
    # Pull one chunk with the backlog already in place: it must block
    # until the *new* event lands rather than replaying evt_001.
    pull = asyncio.ensure_future(anext(stream))  # type: ignore[arg-type]
    await asyncio.sleep(0.05)
    assert not pull.done()

    await store.upsert_events([_event(run_id="run_a", seq=1, event_id="evt_002")])
    chunk = await asyncio.wait_for(pull, timeout=5.0)

    assert chunk.startswith("id: evt_002")
    await stream.aclose()


async def test_stream_project_events__resume_cursor_beats_tail() -> None:
    """Last-Event-ID wins over tail — a reconnecting client must get the
    events it missed, which is the entire point of the resume header."""
    store = InMemoryTraceStore()
    await store.upsert_run(_run(run_id="run_a", project_id="proj_a"))
    await store.upsert_events(
        [
            _event(run_id="run_a", seq=0, event_id="evt_001"),
            _event(run_id="run_a", seq=1, event_id="evt_002"),
        ]
    )

    chunks = await _collect(
        stream_project_events(
            store,
            "proj_a",
            after_event_id="evt_001",
            is_disconnected=_DisconnectAfterN(1),
            tail=True,
            poll_interval=0.01,
        )
    )

    assert len(chunks) == 1
    assert chunks[0].startswith("id: evt_002")


async def test_latest_event_id__is_scoped_to_the_project_and_none_when_empty() -> None:
    store = InMemoryTraceStore()
    assert await store.latest_event_id(None) is None

    await store.upsert_run(_run(run_id="run_a", project_id="proj_a"))
    await store.upsert_run(_run(run_id="run_b", project_id="proj_b"))
    await store.upsert_events(
        [
            _event(run_id="run_a", seq=0, event_id="evt_001"),
            _event(run_id="run_b", seq=0, event_id="evt_009"),
        ]
    )

    assert await store.latest_event_id("proj_a") == "evt_001"
    assert await store.latest_event_id("proj_b") == "evt_009"
    assert await store.latest_event_id(None) == "evt_009"
    assert await store.latest_event_id("proj_missing") is None


@pytest.fixture
def trace_store() -> InMemoryTraceStore:
    return InMemoryTraceStore()


@pytest.fixture
def client(
    tmp_path: Path,
    trace_store: InMemoryTraceStore,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.setattr(live_module, "LATE_EVENT_GRACE_SECONDS", 0.0)
    settings = Settings(
        # Both workers off - see conftest.py and test_api_query.py: a real
        # worker against CI's live Redis blocks TestClient teardown.
        blob_root=str(tmp_path / "blobs"),
        feature_store_worker=False,
        feature_detector_worker=False,
    )
    app = create_app(settings)
    app.dependency_overrides[get_trace_store] = lambda: trace_store
    with TestClient(app) as test_client:
        yield test_client


async def test_live_run_endpoint__streams_sse_and_completes_for_a_finished_run(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    await trace_store.upsert_events(
        [
            _event(seq=0, kind="run.started"),
            _event(seq=1, kind="run.finished"),
        ]
    )

    response = client.get("/v1/live/runs/run_1")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "id: 0" in response.text
    assert "run.started" in response.text
    assert "id: 1" in response.text
    assert "run.finished" in response.text


async def test_live_run_endpoint__last_event_id_header_resumes(
    client: TestClient, trace_store: InMemoryTraceStore
) -> None:
    await trace_store.upsert_events(
        [
            _event(seq=0, kind="run.started"),
            _event(seq=1, kind="run.finished"),
        ]
    )

    response = client.get("/v1/live/runs/run_1", headers={"Last-Event-ID": "0"})

    assert "run.started" not in response.text
    assert "run.finished" in response.text


async def test_firehose_resolves_the_project_filter_by_name() -> None:
    """The firehose takes the same ``?project=`` values the query API does.

    Fixing name resolution on /v1/runs and /v1/stats but not here left
    scripts/smoke/phase2.sh subscribing by name and receiving nothing at
    all, while the very same run asserted fine through the query API.
    Hence one shared resolver rather than a rule to remember at each
    call site.

    Asserted through the helper rather than over HTTP: the firehose has
    no terminal condition, so a TestClient request to it never returns.
    """
    store = InMemoryTraceStore()
    await store.ensure_project("proj_hashed", "phase2-smoke")

    assert await resolve_project_id(store, "phase2-smoke") == "proj_hashed"
    assert await resolve_project_id(store, "proj_hashed") == "proj_hashed"
    assert await resolve_project_id(store, None) is None
    # Unknown stays unchanged: it must match nothing, never widen to all.
    assert await resolve_project_id(store, "no-such-project") == "no-such-project"


async def test_stream_project_events__resolves_a_late_appearing_name() -> None:
    """Subscribing by name before the project exists must still work.

    A one-shot resolution at subscribe time looked correct and passed
    every unit test, but scripts/smoke/phase2.sh opens the firehose
    against an empty database and *then* starts the agent: with no name
    to match yet, the filter kept the raw string forever and the
    subscriber received nothing for a project that did start producing
    events seconds later.
    """
    store = InMemoryTraceStore()
    stream = stream_project_events(
        store,
        "phase2-smoke",  # nothing in the store knows this name yet
        after_event_id=None,
        is_disconnected=_never_disconnected,
        poll_interval=0.01,
    )
    pull = asyncio.ensure_future(anext(stream))  # type: ignore[arg-type]
    await asyncio.sleep(0.05)
    assert not pull.done()

    # The agent starts: the project and its first event appear together.
    await store.ensure_project("proj_hashed", "phase2-smoke")
    await store.upsert_run(_run(run_id="run_a", project_id="proj_hashed"))
    await store.upsert_events(
        [_event(run_id="run_a", seq=0, event_id="evt_001", kind="run.started")]
    )

    chunk = await asyncio.wait_for(pull, timeout=5.0)

    assert chunk.startswith("id: evt_001")
    assert "run.started" in chunk
    await stream.aclose()
