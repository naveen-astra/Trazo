"""Unit tests for trazo.replay (TRZ-P4-05)."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

from trazo import replay
from trazo.core.fingerprint import fingerprint_for
from trazo.core.replay_bundle import RecordedEvent, ReplayBundle


@pytest.fixture(autouse=True)
def _reset_entrypoints() -> None:
    replay._reset_entrypoints_for_tests()
    yield
    replay._reset_entrypoints_for_tests()


def _event(
    seq: int,
    kind: str,
    payload: dict[str, Any],
    *,
    step_id: str | None = None,
    fingerprint: str | None = None,
) -> RecordedEvent:
    return RecordedEvent(
        run_id="run_1",
        seq=seq,
        event_id=f"evt_{seq}",
        kind=kind,
        ts="2026-01-01T00:00:00Z",
        step_id=step_id,
        agent_id=None,
        fingerprint=fingerprint,
        payload=payload,
        blobs=[],
    )


def _bundle(
    events: list[RecordedEvent],
    *,
    framework: str = "langgraph",
    project_id: str = "proj_1",
) -> ReplayBundle:
    by_kind: dict[str, list[RecordedEvent]] = defaultdict(list)
    for event in events:
        by_kind[event.kind].append(event)
    return ReplayBundle(
        run_id="run_1",
        project_id=project_id,
        framework=framework,
        status="ok",
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:00:05Z",
        tags={},
        totals={},
        event_count=len(events),
        blob_manifest=[],
        events=events,
        _events_by_kind=dict(by_kind),
    )


# --- entrypoint registration ---


def test_entrypoint__decorator_form_registers_a_default() -> None:
    @replay.entrypoint
    def run(entry_input: object) -> str:
        return "ran"

    assert replay._registered_entrypoint("anything") is run


def test_entrypoint__framework_scoped_registration() -> None:
    @replay.entrypoint(framework="langgraph")
    def run_langgraph(entry_input: object) -> str:
        return "langgraph"

    @replay.entrypoint(framework="crewai")
    def run_crewai(entry_input: object) -> str:
        return "crewai"

    assert replay._registered_entrypoint("langgraph") is run_langgraph
    assert replay._registered_entrypoint("crewai") is run_crewai


def test_run_to__raises_when_nothing_registered() -> None:
    session = replay.Session(_bundle([]))

    with pytest.raises(replay.NoEntrypointRegisteredError, match="langgraph"):
        session.run_to()


# --- Session.steps() ---


def test_steps__pairs_started_and_finished_events() -> None:
    bundle = _bundle(
        [
            _event(
                0,
                "step.started",
                {"name": "plan", "state_before": {"x": 1}},
                step_id="stp_0",
            ),
            _event(
                1,
                "step.finished",
                {"status": "ok", "state_after": {"x": 2}},
                step_id="stp_0",
            ),
            _event(
                2,
                "step.started",
                {"name": "search", "state_before": {"x": 2}},
                step_id="stp_1",
            ),
            _event(
                3,
                "step.finished",
                {"status": "ok", "state_after": {"x": 3}},
                step_id="stp_1",
            ),
        ]
    )
    session = replay.Session(bundle)

    steps = session.steps()

    assert [s.name for s in steps] == ["plan", "search"]
    assert [s.index for s in steps] == [0, 1]
    assert steps[0].state_before == {"x": 1}
    assert steps[0].state_after == {"x": 2}


def test_steps__gathers_boundary_events_by_step_id() -> None:
    bundle = _bundle(
        [
            _event(
                0, "step.started", {"name": "plan", "state_before": {}}, step_id="stp_0"
            ),
            _event(1, "llm.call", {"response": "a"}, step_id="stp_0"),
            _event(2, "tool.call", {"result": "b"}, step_id="stp_0"),
            _event(
                3, "step.finished", {"status": "ok", "state_after": {}}, step_id="stp_0"
            ),
        ]
    )
    session = replay.Session(bundle)

    [step] = session.steps()

    assert [e.kind for e in step.boundary_events] == ["llm.call", "tool.call"]


def test_steps__resolves_offloaded_state_via_blob_fetch(tmp_path: Path) -> None:
    import httpx

    state = {"messages": ["hi"]}
    state_bytes = json.dumps(state).encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/blobs/sha256:abc"
        return httpx.Response(200, content=state_bytes)

    bundle = _bundle(
        [
            _event(
                0,
                "step.started",
                {"name": "plan", "state_before": {"$blob": "sha256:abc"}},
                step_id="stp_0",
            ),
        ]
    )
    session = replay.Session(
        bundle, endpoint="http://example.test", cache_dir=tmp_path, api_key="k"
    )

    # Monkeypatch the blob fetch to use our mock transport.
    import trazo.replay as replay_module

    original_fetch = replay_module.fetch_blob
    keys_seen: list[str | None] = []

    def fake_fetch_blob(
        sha256: str,
        *,
        endpoint: str,
        cache_dir: Path,
        api_key: str | None = None,
        client: object = None,
    ) -> bytes:
        keys_seen.append(api_key)
        return original_fetch(
            sha256,
            endpoint=endpoint,
            api_key=api_key,
            cache_dir=cache_dir,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    replay_module.fetch_blob = fake_fetch_blob  # type: ignore[assignment]
    try:
        [step] = session.steps()
        assert step.state_before == state
        # The session's key reaches the lazy blob fetch, which a secured
        # control plane requires on every read.
        assert keys_seen == ["k"]
    finally:
        replay_module.fetch_blob = original_fetch  # type: ignore[assignment]


def test_state_after__is_none_when_no_finished_event() -> None:
    bundle = _bundle(
        [
            _event(
                0, "step.started", {"name": "plan", "state_before": {}}, step_id="stp_0"
            )
        ]
    )
    session = replay.Session(bundle)

    [step] = session.steps()

    assert step.state_after is None


# --- Session.run_to() ---


def test_run_to__invokes_the_registered_entrypoint_with_entry_input() -> None:
    llm_payload = {
        "provider": "fixture",
        "model": "fixture-v1",
        "params": {},
        "messages_in": {"question": "hi"},
        "response": "hello",
        "tokens_in": 1,
        "tokens_out": 1,
        "cost_usd": 0.0,
        "latency_ms": 1.0,
    }
    bundle = _bundle(
        [
            _event(0, "run.started", {"entry_input": {"question": "hi"}}),
            _event(
                1,
                "llm.call",
                llm_payload,
                fingerprint=fingerprint_for("llm.call", llm_payload),
            ),
        ]
    )
    session = replay.Session(bundle)
    received_input = {}

    @replay.entrypoint(framework="langgraph")
    def run(entry_input: object) -> str:
        received_input["value"] = entry_input
        from trazo.core.runtime import get_recorder

        result = get_recorder().boundary(
            "llm.call",
            {
                "provider": "fixture",
                "model": "fixture-v1",
                "params": {},
                "messages_in": {"question": "hi"},
            },
            lambda: {},
        )
        return str(result["response"])

    report = session.run_to()

    assert received_input["value"] == {"question": "hi"}
    assert report.fidelity == 1.0
    assert report.divergences == []


def test_run_to__does_not_permanently_install_the_replay_recorder() -> None:
    """After run_to() returns, the process-wide recorder must be back to
    whatever it was before (TRZ-P4-05's replay_recorder_scope guarantee)."""
    from trazo.core import runtime

    assert runtime.is_initialized() is False

    bundle = _bundle([_event(0, "run.started", {"entry_input": None})])
    session = replay.Session(bundle)

    @replay.entrypoint(framework="langgraph")
    def run(entry_input: object) -> None:
        assert runtime.is_initialized() is True

    session.run_to()


def test_run_to__makes_get_config_project_available_to_the_entrypoint() -> None:
    """Real bug found running this against an actual demo (TRZ-P4-07):
    LangGraph/CrewAI adapters call get_config().project just like a live
    run does — run_to() must make that work without a real trazo.init()
    ever having been called, using the bundle's own project_id."""
    from trazo.core.context import get_config, is_initialized

    assert is_initialized() is False

    bundle = _bundle(
        [_event(0, "run.started", {"entry_input": None})],
        project_id="the-bundles-project",
    )
    session = replay.Session(bundle)
    seen_project = {}

    @replay.entrypoint(framework="langgraph")
    def run(entry_input: object) -> None:
        seen_project["value"] = get_config().project

    session.run_to()

    assert seen_project["value"] == "the-bundles-project"
    assert is_initialized() is False
