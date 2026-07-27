"""Unit tests for trazo.core.runtime and the public trazo.init() orchestration
(TRZ-P2-03)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

import trazo
from trazo.core import context, runtime
from trazo.core.context import run_scope
from trazo.core.recorder import Recorder
from trazo.errors import NotInitializedError


def test_get_recorder__before_init_raises_not_initialized() -> None:
    assert runtime.is_initialized() is False
    with pytest.raises(NotInitializedError):
        runtime.get_recorder()


def test_init_recorder__installs_a_recorder_using_the_given_client(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json={"accepted": 0})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    recorder = runtime.init_recorder(
        endpoint="http://example.test",
        api_key="k",
        spool_root=tmp_path,
        client=client,
    )

    assert isinstance(recorder, Recorder)
    assert runtime.get_recorder() is recorder


def test_trazo_init__wires_config_and_starts_a_recorder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The public orchestrator: resolves config, then installs a real
    Recorder. Run from a temp cwd so the default `.trazo/spool` lands
    somewhere disposable, and against an endpoint nothing listens on so
    the (fast, connection-refused) failure never blocks the test."""
    monkeypatch.chdir(tmp_path)

    trazo.init(project="research-assistant", endpoint="http://127.0.0.1:1", api_key="k")

    assert context.get_config().project == "research-assistant"
    assert runtime.is_initialized() is True


def test_trazo_shutdown__flushes_the_installed_recorder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The public flush-before-exit call (TRZ-P3-02): short-lived
    processes can't rely on atexit alone — confirmed empirically while
    building the research-assistant demo, where most of a run's events
    were still queued when the process exited a few hundred ms after the
    graph finished."""
    monkeypatch.chdir(tmp_path)
    posted_batches: list[list[dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        posted_batches.append(json.loads(request.content)["events"])
        return httpx.Response(202, json={"accepted": 1})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    runtime.init_recorder(endpoint="http://example.test", api_key="k", client=client)

    with run_scope("shutdown-test"):
        runtime.get_recorder().emit("run.started", {"framework": "custom", "tags": {}})
    trazo.shutdown()

    assert posted_batches, "shutdown() must flush the queued event before returning"
