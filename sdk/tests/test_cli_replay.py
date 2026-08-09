"""Unit tests for trazo.cli.replay (TRZ-P4-06)."""

from __future__ import annotations

import io
import json
from collections import defaultdict
from pathlib import Path

import httpx
import pytest

from trazo import replay as replay_module
from trazo.cli.replay import run_replay, run_verify
from trazo.core.fingerprint import fingerprint_for
from trazo.core.replay_bundle import RecordedEvent


@pytest.fixture(autouse=True)
def _reset_entrypoints() -> None:
    replay_module._reset_entrypoints_for_tests()
    yield
    replay_module._reset_entrypoints_for_tests()


def _event(seq: int, kind: str, payload: dict[str, object]) -> RecordedEvent:
    fingerprint = None
    if kind in (
        "llm.call",
        "tool.call",
        "memory.read",
        "memory.write",
        "human.checkpoint",
    ):
        fingerprint = fingerprint_for(kind, payload)
    return RecordedEvent(
        run_id="run_1",
        seq=seq,
        event_id=f"evt_{seq}",
        kind=kind,
        ts="2026-01-01T00:00:00Z",
        step_id=None,
        agent_id=None,
        fingerprint=fingerprint,
        payload=payload,
        blobs=[],
    )


def _write_bundle_cache(cache_dir: Path, events: list[RecordedEvent]) -> None:
    by_kind: dict[str, list[RecordedEvent]] = defaultdict(list)
    for event in events:
        by_kind[event.kind].append(event)
    manifest = {
        "schema": "trazo.replay-bundle.v1",
        "run_id": "run_1",
        "project_id": "proj_1",
        "framework": "langgraph",
        "status": "ok",
        "started_at": "2026-01-01T00:00:00Z",
        "finished_at": "2026-01-01T00:00:05Z",
        "tags": {},
        "totals": {},
        "event_count": len(events),
        "blob_manifest": [],
    }
    lines = [json.dumps(manifest)]
    for e in events:
        lines.append(
            json.dumps(
                {
                    "run_id": e.run_id,
                    "seq": e.seq,
                    "event_id": e.event_id,
                    "kind": e.kind,
                    "ts": e.ts,
                    "step_id": e.step_id,
                    "agent_id": e.agent_id,
                    "fingerprint": e.fingerprint,
                    "payload": e.payload,
                    "blobs": e.blobs,
                }
            )
        )
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "run_1.ndjson").write_text("\n".join(lines) + "\n", encoding="utf-8")


_LLM_PAYLOAD = {
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


def _run_to_llm_call(entry_input: object) -> str:
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


def test_run_replay__clean_replay_exits_0_and_prints_fidelity(tmp_path: Path) -> None:
    _write_bundle_cache(
        tmp_path,
        [
            _event(0, "run.started", {"entry_input": None}),
            _event(1, "llm.call", _LLM_PAYLOAD),
        ],
    )
    replay_module.entrypoint(_run_to_llm_call, framework="langgraph")
    out = io.StringIO()

    exit_code = run_replay(
        "run_1", endpoint="http://example.test", cache_dir=tmp_path, out=out
    )

    assert exit_code == 0
    assert "boundary fidelity: 100.00%" in out.getvalue()


def test_run_replay__json_output_is_valid_json(tmp_path: Path) -> None:
    _write_bundle_cache(
        tmp_path,
        [
            _event(0, "run.started", {"entry_input": None}),
            _event(1, "llm.call", _LLM_PAYLOAD),
        ],
    )
    replay_module.entrypoint(_run_to_llm_call, framework="langgraph")
    out = io.StringIO()

    exit_code = run_replay(
        "run_1",
        endpoint="http://example.test",
        cache_dir=tmp_path,
        out=out,
        as_json=True,
    )

    assert exit_code == 0
    body = json.loads(out.getvalue())
    assert body["boundary_fidelity"] == 1.0
    assert body["divergences"] == []


def test_run_replay__strict_mode_divergence_exits_1(tmp_path: Path) -> None:
    _write_bundle_cache(
        tmp_path,
        [
            _event(0, "run.started", {"entry_input": None}),
            _event(1, "llm.call", _LLM_PAYLOAD),
        ],
    )

    def _diverging_entrypoint(entry_input: object) -> str:
        from trazo.core.runtime import get_recorder

        result = get_recorder().boundary(
            "llm.call",
            {
                "provider": "fixture",
                "model": "fixture-v1",
                "params": {},
                "messages_in": {"question": "a completely different question"},
            },
            lambda: {},
        )
        return str(result["response"])

    replay_module.entrypoint(_diverging_entrypoint, framework="langgraph")
    out = io.StringIO()

    exit_code = run_replay(
        "run_1", endpoint="http://example.test", cache_dir=tmp_path, out=out
    )

    assert exit_code == 1
    assert "divergences: 1" in out.getvalue()


def test_run_replay__no_entrypoint_registered_exits_1(tmp_path: Path) -> None:
    _write_bundle_cache(tmp_path, [_event(0, "run.started", {"entry_input": None})])

    exit_code = run_replay("run_1", endpoint="http://example.test", cache_dir=tmp_path)

    assert exit_code == 1


def test_run_replay__bundle_fetch_failure_exits_1_without_crashing(
    tmp_path: Path,
) -> None:
    """No cache and an unreachable endpoint: the CLI must print a clean
    error and exit 1, not surface a raw exception."""
    exit_code = run_replay(
        "run_1", endpoint="http://127.0.0.1:1", cache_dir=tmp_path / "empty"
    )

    assert exit_code == 1


def test_run_verify__reports_boundary_and_state_fidelity(tmp_path: Path) -> None:
    _write_bundle_cache(
        tmp_path,
        [
            _event(0, "run.started", {"entry_input": None}),
            _event(1, "llm.call", _LLM_PAYLOAD),
            _event(2, "run.finished", {"totals": {"duration_ms": 100.0}}),
        ],
    )
    replay_module.entrypoint(_run_to_llm_call, framework="langgraph")
    out = io.StringIO()

    exit_code = run_verify(
        "run_1",
        endpoint="http://example.test",
        cache_dir=tmp_path,
        out=out,
        submit=False,  # submission itself is covered separately below
    )

    assert exit_code == 0
    text = out.getvalue()
    assert "boundary fidelity: 100.00%" in text
    assert "state fidelity:    100.00%" in text
    assert "replay overhead:" in text


def test_run_verify__lenient_even_on_divergence_still_reports_full_stats(
    tmp_path: Path,
) -> None:
    _write_bundle_cache(
        tmp_path,
        [
            _event(0, "run.started", {"entry_input": None}),
            _event(1, "llm.call", _LLM_PAYLOAD),
        ],
    )

    def _diverging_entrypoint(entry_input: object) -> str:
        from trazo.core.runtime import get_recorder

        result = get_recorder().boundary(
            "llm.call",
            {
                "provider": "fixture",
                "model": "fixture-v1",
                "params": {},
                "messages_in": {"question": "drifted"},
            },
            lambda: {},
        )
        return str(result["response"])

    replay_module.entrypoint(_diverging_entrypoint, framework="langgraph")
    out = io.StringIO()

    exit_code = run_verify(
        "run_1",
        endpoint="http://example.test",
        cache_dir=tmp_path,
        out=out,
        as_json=True,
        submit=False,  # submission itself is covered separately below
    )

    assert exit_code == 1  # divergence present, but the run still completed
    body = json.loads(out.getvalue())
    assert len(body["divergences"]) == 1
    assert body["boundary_fidelity"] == 0.0


def test_run_verify__submits_the_report_to_the_control_plane(tmp_path: Path) -> None:
    """The whole point of submission: a real `trazo verify` run's report
    must reach POST /v1/runs/{run_id}/replay-report so the dashboard's
    Replay Studio can show it — not just print to stdout and vanish."""
    _write_bundle_cache(
        tmp_path,
        [
            _event(0, "run.started", {"entry_input": None}),
            _event(1, "llm.call", _LLM_PAYLOAD),
            _event(2, "run.finished", {"totals": {"duration_ms": 100.0}}),
        ],
    )
    replay_module.entrypoint(_run_to_llm_call, framework="langgraph")

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    exit_code = run_verify(
        "run_1",
        endpoint="http://example.test",
        api_key="test-key",
        cache_dir=tmp_path,
        out=io.StringIO(),
        submit_client=client,
    )

    assert exit_code == 0
    [request] = requests
    assert request.method == "POST"
    assert request.url.path == "/v1/runs/run_1/replay-report"
    assert request.headers["authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert body["boundary_fidelity"] == 1.0
    assert body["state_fidelity"] == 1.0
    assert body["divergences"] == []
    assert "replay_overhead" in body


def test_run_verify__submission_failure_does_not_fail_the_command(
    tmp_path: Path,
) -> None:
    """Best-effort: an unreachable control plane must not turn a
    successful verification into a failed command — the report was
    already computed and printed regardless."""
    _write_bundle_cache(
        tmp_path,
        [
            _event(0, "run.started", {"entry_input": None}),
            _event(1, "llm.call", _LLM_PAYLOAD),
            _event(2, "run.finished", {"totals": {"duration_ms": 100.0}}),
        ],
    )
    replay_module.entrypoint(_run_to_llm_call, framework="langgraph")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    out = io.StringIO()

    exit_code = run_verify(
        "run_1",
        endpoint="http://example.test",
        cache_dir=tmp_path,
        out=out,
        submit_client=client,
    )

    assert exit_code == 0
    assert "boundary fidelity: 100.00%" in out.getvalue()
