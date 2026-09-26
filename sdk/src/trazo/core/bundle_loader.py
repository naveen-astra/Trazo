"""Fetches a replay bundle over HTTP and caches it on disk (TRZ-P4-01):
``.trazo/cache/<run_id>.ndjson`` for the bundle itself, ``.trazo/cache/
blobs/<sha256>`` for lazily-fetched blobs (REPLAY_ENGINE.md §7).

Only a bundle whose run is no longer ``running`` is cached — the control
plane's own ``Cache-Control`` header says as much (query.py's
``get_replay_bundle``), but this SDK-side cache also needs to make that
call itself since httpx's plain ``Client`` doesn't do HTTP caching for
us: a cache hit must never look up a run that could still be receiving
events.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from trazo.core.replay_bundle import ReplayBundle

_DEFAULT_CACHE_DIR = Path(".trazo/cache")
_TIMEOUT_SECONDS = 30.0


class BundleFetchError(Exception):
    """Raised when the replay bundle can't be fetched — network failure
    or a non-2xx response. Never silently returns an empty bundle."""


def _bundle_cache_path(cache_dir: Path, run_id: str) -> Path:
    return cache_dir / f"{run_id}.ndjson"


def load_bundle(
    run_id: str,
    *,
    endpoint: str,
    api_key: str | None = None,
    cache_dir: Path = _DEFAULT_CACHE_DIR,
    client: httpx.Client | None = None,
) -> ReplayBundle:
    """Fetch (or reuse a cached) replay bundle for ``run_id``.

    A cached copy is only ever written for a run that had already
    finished (or errored) at fetch time — see the module docstring —
    so a cache hit is always safe to trust without re-validating.
    """
    cache_path = _bundle_cache_path(cache_dir, run_id)
    if cache_path.exists():
        return ReplayBundle.parse_ndjson(cache_path.read_bytes())

    owns_client = client is None
    http_client = client or httpx.Client(timeout=_TIMEOUT_SECONDS)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        response = http_client.get(
            f"{endpoint}/v1/runs/{run_id}/replay-bundle", headers=headers
        )
    except httpx.HTTPError as exc:
        raise BundleFetchError(f"request to {endpoint} failed: {exc}") from exc
    finally:
        if owns_client:
            http_client.close()

    if response.status_code != 200:
        raise BundleFetchError(
            f"{endpoint} returned {response.status_code}: {response.text}"
        )

    data = response.content
    bundle = ReplayBundle.parse_ndjson(data)

    if bundle.status != "running":
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(data)

    return bundle


def _blob_cache_path(cache_dir: Path, sha256: str) -> Path:
    digest = sha256.removeprefix("sha256:")
    return cache_dir / "blobs" / digest


def fetch_blob(
    sha256: str,
    *,
    endpoint: str,
    api_key: str | None = None,
    cache_dir: Path = _DEFAULT_CACHE_DIR,
    client: httpx.Client | None = None,
) -> bytes:
    """Fetch (or reuse a cached copy of) one blob, content-addressed by
    ``sha256`` — always cacheable forever, unlike a bundle (a blob's
    content can never change once it exists; only a still-running run's
    *bundle* can grow new events)."""
    cache_path = _blob_cache_path(cache_dir, sha256)
    if cache_path.exists():
        return cache_path.read_bytes()

    owns_client = client is None
    http_client = client or httpx.Client(timeout=_TIMEOUT_SECONDS)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        response = http_client.get(f"{endpoint}/v1/blobs/{sha256}", headers=headers)
    except httpx.HTTPError as exc:
        raise BundleFetchError(f"request to {endpoint} failed: {exc}") from exc
    finally:
        if owns_client:
            http_client.close()

    if response.status_code != 200:
        raise BundleFetchError(
            f"{endpoint} returned {response.status_code}: {response.text}"
        )

    data = response.content
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(data)
    return data
