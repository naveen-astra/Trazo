"""Unit tests for the CrewAI adapter's memory.read/memory.write mapping
(TRZ-P3-01), via the public crewai_event_bus surface rather than a live
memory-enabled crew: CrewAI's default memory backend needs a working
embedder (network access to fetch/run an embedding model), which isn't
available in this environment — the event *shapes* below are taken
directly from crewai.events.types.memory_events's field definitions, not
guessed. See listener.py's module docstring for the same rationale on the
other event pairs, which *are* exercised through a live toy crew.

``crewai_event_bus.emit()`` runs sync handlers on a background
ThreadPoolExecutor and returns a ``Future`` (verified empirically) — a
real crew's own long-running ``kickoff()`` gives handlers plenty of time
to finish between events, but a rapid-fire manual test needs to wait on
that Future explicitly, or collection races the handler thread. Matching
``InstrumentedCrew.kickoff()``'s own call order: register -> emit ->
unregister -> ``process()`` (sorts by emission_sequence and replays into
Recorder) -> assert.
"""

from __future__ import annotations

from typing import Any

from crewai.events.event_bus import crewai_event_bus
from crewai.events.types.memory_events import (
    MemoryQueryCompletedEvent,
    MemoryQueryFailedEvent,
    MemoryQueryStartedEvent,
    MemorySaveCompletedEvent,
    MemorySaveStartedEvent,
)

from trazo.core.context import run_scope
from trazo.core.recorder import Recorder
from trazo.integrations.crewai.listener import CrewEventCapture


class _FakeShipper:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []

    def enqueue(self, event: dict[str, Any]) -> None:
        self.enqueued.append(event)

    def flush_and_stop(self, *, timeout: float = 5.0) -> None:
        pass


def _events_by_kind(events: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [e for e in events if e["kind"] == kind]


def _emit_and_wait(source: Any, event: Any) -> None:
    future = crewai_event_bus.emit(source, event)
    if future is not None:
        future.result(timeout=5.0)


def test_memory_query__emits_memory_read_with_results_and_latency() -> None:
    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)
    capture = CrewEventCapture(recorder)
    capture.register()
    try:
        _emit_and_wait(
            None,
            MemoryQueryStartedEvent(
                query="what is trazo?", limit=5, task_id="t1", agent_role="Researcher"
            ),
        )
        _emit_and_wait(
            None,
            MemoryQueryCompletedEvent(
                query="what is trazo?",
                results=[{"content": "trazo is an SDK", "score": 0.9}],
                limit=5,
                query_time_ms=12.5,
                task_id="t1",
                agent_role="Researcher",
            ),
        )
    finally:
        capture.unregister()

    with run_scope("toy-crew-test"):
        capture.process()

    reads = _events_by_kind(shipper.enqueued, "memory.read")
    assert len(reads) == 1
    payload = reads[0]["payload"]
    assert payload["store"] == "vector"
    assert payload["query"] == "what is trazo?"
    assert payload["k"] == 5
    assert payload["latency_ms"] == 12.5
    assert payload["results"] == [{"content": "trazo is an SDK", "score": 0.9}]
    assert reads[0]["agent_id"] == "Researcher"


def test_memory_save__emits_memory_write_with_value_and_latency() -> None:
    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)
    capture = CrewEventCapture(recorder)
    capture.register()
    try:
        _emit_and_wait(
            None,
            MemorySaveStartedEvent(
                value="trazo is an SDK", task_id="t1", agent_role="Researcher"
            ),
        )
        _emit_and_wait(
            None,
            MemorySaveCompletedEvent(
                value="trazo is an SDK",
                save_time_ms=3.2,
                task_id="t1",
                agent_role="Researcher",
            ),
        )
    finally:
        capture.unregister()

    with run_scope("toy-crew-test"):
        capture.process()

    writes = _events_by_kind(shipper.enqueued, "memory.write")
    assert len(writes) == 1
    payload = writes[0]["payload"]
    assert payload["store"] == "vector"
    assert payload["key_or_ns"] == "Researcher"
    assert payload["value"] == "trazo is an SDK"
    assert payload["latency_ms"] == 3.2


def test_memory_query_failed__drops_the_pending_query_without_emitting() -> None:
    shipper = _FakeShipper()
    recorder = Recorder(shipper=shipper)
    capture = CrewEventCapture(recorder)
    capture.register()
    try:
        _emit_and_wait(
            None,
            MemoryQueryStartedEvent(
                query="q", limit=1, task_id="t1", agent_role="Researcher"
            ),
        )
        _emit_and_wait(
            None,
            MemoryQueryFailedEvent(
                query="q",
                limit=1,
                error="embedder unavailable",
                task_id="t1",
                agent_role="Researcher",
            ),
        )
    finally:
        capture.unregister()

    with run_scope("toy-crew-test"):
        capture.process()

    assert _events_by_kind(shipper.enqueued, "memory.read") == []
