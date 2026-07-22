"""Unit tests for trazo.cli.doctor (TRZ-P2-08)."""

from __future__ import annotations

import io
from pathlib import Path

import httpx
import pytest

from trazo import __version__ as sdk_version
from trazo.cli.doctor import run_doctor
from trazo.core.spool import DiskSpool


def _client(status_code: int = 200, version: str | None = None) -> httpx.Client:
    reported = version if version is not None else sdk_version

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"status": "ok", "version": reported})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_run_doctor__all_pass_when_reachable_and_spool_empty(tmp_path: Path) -> None:
    out = io.StringIO()

    exit_code = run_doctor(
        endpoint="http://example.test",
        spool_root=tmp_path / "spool",
        out=out,
        client=_client(),
    )

    assert exit_code == 0
    printed = out.getvalue()
    assert "[PASS] connectivity" in printed
    assert "[PASS] spool" in printed
    assert "[PASS] version" in printed


def test_run_doctor__fails_when_control_plane_unreachable(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    out = io.StringIO()
    exit_code = run_doctor(
        endpoint="http://example.test",
        spool_root=tmp_path / "spool",
        out=out,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert exit_code == 1
    assert "[FAIL] connectivity" in out.getvalue()


def test_run_doctor__reports_pending_spool_batches(tmp_path: Path) -> None:
    spool_root = tmp_path / "spool"
    DiskSpool(spool_root).write([{"seq": 0}])

    out = io.StringIO()
    exit_code = run_doctor(
        endpoint="http://example.test", spool_root=spool_root, out=out, client=_client()
    )

    assert exit_code == 0
    assert "1 batch(es) queued" in out.getvalue()


def test_run_doctor__fails_when_spool_is_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "TRAZO_SPOOL_MAX_MB", "0.000001"
    )  # ~1 byte — any batch overflows it
    spool_root = tmp_path / "spool"
    DiskSpool(spool_root, max_bytes=1).write([{"seq": 0}])

    out = io.StringIO()
    exit_code = run_doctor(
        endpoint="http://example.test", spool_root=spool_root, out=out, client=_client()
    )

    assert exit_code == 1
    assert "[FAIL] spool" in out.getvalue()


def test_run_doctor__reports_version_mismatch_as_informational(tmp_path: Path) -> None:
    out = io.StringIO()
    exit_code = run_doctor(
        endpoint="http://example.test",
        spool_root=tmp_path / "spool",
        out=out,
        client=_client(version="9.9.9"),
    )

    assert exit_code == 0
    assert "skew" in out.getvalue()


def test_run_doctor__version_unknown_when_unreachable(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    out = io.StringIO()
    run_doctor(
        endpoint="http://example.test",
        spool_root=tmp_path / "spool",
        out=out,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert "server unknown" in out.getvalue()
