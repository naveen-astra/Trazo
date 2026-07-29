"""Integration test for HttpOpaClient against a real, locally-spawned OPA
process serving the actual policies/trazo bundle (TRZ-P6-01/03).

Skipped automatically when no `opa` binary is on PATH (same "self-skip
gracefully" convention as test_trace_store_postgres.py) -- CI's `opa`
job installs one (ci.yml), and this repo's own bundle was verified
against that exact pinned version (0.70.0) while building it (see
policies/README.md and the TRZ-P6-01 commit history).
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from trazo_server.policy.opa_client import HttpOpaClient

_REPO_ROOT = Path(__file__).resolve().parents[2]
_POLICIES_DIR = _REPO_ROOT / "policies" / "trazo"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def opa_base_url() -> Iterator[str]:
    opa_bin = shutil.which("opa")
    if opa_bin is None:
        pytest.skip("no `opa` binary on PATH — install one for this integration test")

    port = _free_port()
    proc = subprocess.Popen(
        [opa_bin, "run", "--server", "--addr", f":{port}", str(_POLICIES_DIR)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_opa(base_url)
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _wait_for_opa(base_url: str, *, timeout_seconds: float = 10.0) -> None:
    import httpx

    deadline = time.monotonic() + timeout_seconds
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            httpx.get(f"{base_url}/health", timeout=0.5).raise_for_status()
            return
        except Exception as exc:  # retry until timeout
            last_exc = exc
            time.sleep(0.1)
    raise RuntimeError(f"opa server never became healthy: {last_exc}")


async def test_evaluate__allows_a_clean_read_only_action(opa_base_url: str) -> None:
    client = HttpOpaClient(base_url=opa_base_url)

    result = await client.evaluate(
        {
            "run_id": "run_1",
            "action": {
                "kind": "tool.call",
                "fingerprint": "sha256:" + "a" * 64,
                "tool_name": "web_search",
                "side_effect_class": "read",
                "projected_cost_usd": 0.1,
            },
            "run_context": {"cost_usd_so_far": 0.5, "active_detections": []},
        }
    )

    assert result["decision"] == "allow"
    assert result["policy_id"] == ""


async def test_evaluate__denies_a_blocklisted_tool(opa_base_url: str) -> None:
    client = HttpOpaClient(base_url=opa_base_url)

    result = await client.evaluate(
        {
            "run_id": "run_1",
            "action": {
                "kind": "tool.call",
                "fingerprint": "sha256:" + "a" * 64,
                "tool_name": "delete_database",
                "side_effect_class": "external",
                "projected_cost_usd": 0.1,
            },
            "run_context": {"cost_usd_so_far": 0.5, "active_detections": []},
        }
    )

    assert result["decision"] == "deny"
    assert result["policy_id"] == "tool_blocklist"


async def test_evaluate__real_round_trip_stays_within_the_150ms_latency_budget(
    opa_base_url: str,
) -> None:
    """TRZ-P6-03's DoD: "Latency budget asserted in integration test" --
    a real HTTP round trip to a real OPA process, not a mock."""
    client = HttpOpaClient(base_url=opa_base_url)

    start = time.perf_counter()
    await client.evaluate(
        {
            "run_id": "run_1",
            "action": {
                "kind": "tool.call",
                "fingerprint": "sha256:" + "a" * 64,
                "tool_name": "web_search",
                "side_effect_class": "read",
                "projected_cost_usd": 0.1,
            },
            "run_context": {"cost_usd_so_far": 0.5, "active_detections": []},
        }
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert elapsed_ms < 150, f"OPA round trip took {elapsed_ms:.1f}ms, over budget"
