"""Tests for the trace labels demos record under, and the replay CLI's
adoption of a recorded run's labels."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import replay_cli
from live_llm import TRACE_MODEL_ENV, TRACE_PROVIDER_ENV, trace_labels


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        TRACE_PROVIDER_ENV,
        TRACE_MODEL_ENV,
        "TRAZO_DEMO_LLM_BASE_URL",
        "TRAZO_DEMO_LLM_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_trace_labels__fixture_run() -> None:
    assert trace_labels(live=False) == ("fixture", "fixture-v1")


def test_trace_labels__live_run_names_the_configured_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRAZO_DEMO_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("TRAZO_DEMO_LLM_MODEL", "qwen2.5:3b")

    assert trace_labels(live=True) == ("ollama", "qwen2.5:3b")


def test_trace_labels__explicit_labels_win(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TRACE_PROVIDER_ENV, "ollama")
    monkeypatch.setenv(TRACE_MODEL_ENV, "qwen2.5:3b")

    assert trace_labels(live=False) == ("ollama", "qwen2.5:3b")


def _session_with_llm_payloads(*payloads: dict[str, Any]) -> Any:
    events = [SimpleNamespace(payload=p) for p in payloads]
    bundle = SimpleNamespace(
        events_by_kind=lambda kind: events if kind == "llm.call" else []
    )
    return SimpleNamespace(bundle=bundle)


def test_adopt_recorded_labels__sets_the_recorded_runs_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session_with_llm_payloads(
        {"provider": "ollama", "model": "qwen2.5:3b"},
        {"provider": "other", "model": "ignored"},
    )
    monkeypatch.setattr(replay_cli.replay, "load", lambda *a, **k: session)

    labels = replay_cli.adopt_recorded_labels("run_1", endpoint="x", api_key=None)

    assert labels == ("ollama", "qwen2.5:3b")
    assert trace_labels(live=False) == ("ollama", "qwen2.5:3b")


def test_adopt_recorded_labels__leaves_labels_set_by_hand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(TRACE_PROVIDER_ENV, "fixture")
    monkeypatch.setenv(TRACE_MODEL_ENV, "fixture-v1")

    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("must not fetch when labels are already set")

    monkeypatch.setattr(replay_cli.replay, "load", fail)

    assert replay_cli.adopt_recorded_labels("run_1", endpoint="x", api_key=None) is None
    assert trace_labels(live=False) == ("fixture", "fixture-v1")


def test_adopt_recorded_labels__a_run_without_model_calls_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session_with_llm_payloads()
    monkeypatch.setattr(replay_cli.replay, "load", lambda *a, **k: session)

    assert replay_cli.adopt_recorded_labels("run_1", endpoint="x", api_key=None) is None
    assert trace_labels(live=False) == ("fixture", "fixture-v1")


def test_adopt_recorded_labels__a_failed_fetch_is_left_to_the_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("control plane unreachable")

    monkeypatch.setattr(replay_cli.replay, "load", fail)

    assert replay_cli.adopt_recorded_labels("run_1", endpoint="x", api_key=None) is None
