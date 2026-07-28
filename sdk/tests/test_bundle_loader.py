"""Unit tests for trazo.core.bundle_loader (TRZ-P4-01)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from trazo.core.bundle_loader import BundleFetchError, fetch_blob, load_bundle

_MANIFEST = {
    "schema": "trazo.replay-bundle.v1",
    "run_id": "run_1",
    "project_id": "proj_1",
    "framework": "langgraph",
    "status": "ok",
    "started_at": "2026-01-01T00:00:00Z",
    "finished_at": "2026-01-01T00:00:05Z",
    "tags": {},
    "totals": {},
    "event_count": 1,
    "blob_manifest": [],
}

_EVENT = {
    "run_id": "run_1",
    "seq": 0,
    "event_id": "evt_1",
    "kind": "run.started",
    "ts": "2026-01-01T00:00:00Z",
    "step_id": None,
    "agent_id": None,
    "fingerprint": None,
    "payload": {},
    "blobs": [],
}


def _bundle_bytes(*, status: str = "ok") -> bytes:
    manifest = {**_MANIFEST, "status": status}
    lines = [json.dumps(manifest), json.dumps(_EVENT)]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def test_load_bundle__fetches_and_parses_over_http(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/runs/run_1/replay-bundle"
        return httpx.Response(200, content=_bundle_bytes())

    bundle = load_bundle(
        "run_1",
        endpoint="http://example.test",
        cache_dir=tmp_path,
        client=_client(httpx.MockTransport(handler)),
    )

    assert bundle.run_id == "run_1"
    assert bundle.event_count == 1


def test_load_bundle__sends_bearer_auth_header(tmp_path: Path) -> None:
    seen_headers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers.get("authorization", ""))
        return httpx.Response(200, content=_bundle_bytes())

    load_bundle(
        "run_1",
        endpoint="http://example.test",
        api_key="secret",
        cache_dir=tmp_path,
        client=_client(httpx.MockTransport(handler)),
    )

    assert seen_headers == ["Bearer secret"]


def test_load_bundle__caches_a_finished_bundle_to_disk(tmp_path: Path) -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, content=_bundle_bytes(status="ok"))

    load_bundle(
        "run_1",
        endpoint="http://example.test",
        cache_dir=tmp_path,
        client=_client(httpx.MockTransport(handler)),
    )
    load_bundle(
        "run_1",
        endpoint="http://example.test",
        cache_dir=tmp_path,
        client=_client(httpx.MockTransport(handler)),
    )

    assert call_count == 1  # second call was a cache hit, no network request
    assert (tmp_path / "run_1.ndjson").exists()


def test_load_bundle__never_caches_a_still_running_run(tmp_path: Path) -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, content=_bundle_bytes(status="running"))

    load_bundle(
        "run_1",
        endpoint="http://example.test",
        cache_dir=tmp_path,
        client=_client(httpx.MockTransport(handler)),
    )
    load_bundle(
        "run_1",
        endpoint="http://example.test",
        cache_dir=tmp_path,
        client=_client(httpx.MockTransport(handler)),
    )

    assert call_count == 2  # never cached: fetched fresh both times
    assert not (tmp_path / "run_1.ndjson").exists()


def test_load_bundle__non_200_raises_bundle_fetch_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="no such run")

    with pytest.raises(BundleFetchError, match="404"):
        load_bundle(
            "run_1",
            endpoint="http://example.test",
            cache_dir=tmp_path,
            client=_client(httpx.MockTransport(handler)),
        )


def test_fetch_blob__fetches_and_caches_by_sha(tmp_path: Path) -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        assert request.url.path == "/v1/blobs/sha256:abc123"
        return httpx.Response(200, content=b'{"hello":"world"}')

    data1 = fetch_blob(
        "sha256:abc123",
        endpoint="http://example.test",
        cache_dir=tmp_path,
        client=_client(httpx.MockTransport(handler)),
    )
    data2 = fetch_blob(
        "sha256:abc123",
        endpoint="http://example.test",
        cache_dir=tmp_path,
        client=_client(httpx.MockTransport(handler)),
    )

    assert data1 == data2 == b'{"hello":"world"}'
    assert call_count == 1  # second was a cache hit
    assert (tmp_path / "blobs" / "abc123").exists()


def test_fetch_blob__404_raises_bundle_fetch_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="no such blob")

    with pytest.raises(BundleFetchError, match="404"):
        fetch_blob(
            "sha256:abc123",
            endpoint="http://example.test",
            cache_dir=tmp_path,
            client=_client(httpx.MockTransport(handler)),
        )
