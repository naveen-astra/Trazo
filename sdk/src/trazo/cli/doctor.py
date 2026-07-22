"""``trazo doctor`` — connectivity, spool status, version skew (SDK.md §5).

Three independent checks, each printed with a PASS/WARN/FAIL marker:

- **connectivity**: can we reach the control plane's ``GET /healthz``?
- **spool**: how many batches are queued in the local disk spool
  (``trazo.core.spool.DiskSpool``, TRZ-P2-03), and is it full?
- **version**: does the installed SDK's ``__version__`` match the control
  plane's reported version?

Only connectivity failing or the spool being full are treated as hard
failures (exit 1) — a version mismatch is informational during active
development, where the two packages are not always released in lockstep.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import NamedTuple, TextIO

import httpx

from trazo import __version__ as sdk_version
from trazo.core.spool import DiskSpool, max_bytes_from_env

_DEFAULT_SPOOL_ROOT = Path(".trazo/spool")


class CheckResult(NamedTuple):
    name: str
    ok: bool
    detail: str


def _check_connectivity(
    endpoint: str, client: httpx.Client | None = None
) -> tuple[CheckResult, str | None]:
    """Returns the connectivity result and the server's reported version
    (``None`` if unreachable, so the version check can report "unknown").

    ``client`` is injectable (a real ``httpx.Client`` is built by default)
    so tests can pass one wired to an ``httpx.MockTransport``.
    """
    url = f"{endpoint}/healthz"
    owns_client = client is None
    client = client or httpx.Client()
    try:
        response = client.get(url, timeout=5.0)
    except httpx.HTTPError as exc:
        return CheckResult("connectivity", False, f"could not reach {url}: {exc}"), None
    finally:
        if owns_client:
            client.close()
    if response.status_code != 200:
        return CheckResult(
            "connectivity", False, f"{url} -> HTTP {response.status_code}"
        ), None
    server_version = response.json().get("version", "unknown")
    return CheckResult(
        "connectivity", True, f"{url} -> ok (version {server_version})"
    ), server_version


def _check_spool(spool_root: Path) -> CheckResult:
    spool = DiskSpool(spool_root, max_bytes=max_bytes_from_env())
    pending = spool.pending_batch_count()
    if spool.is_full():
        return CheckResult(
            "spool", False, f"{spool_root} is FULL ({pending} batches queued)"
        )
    if pending:
        return CheckResult(
            "spool",
            True,
            f"{spool_root}: {pending} batch(es) queued, draining on next ship",
        )
    return CheckResult("spool", True, f"{spool_root}: empty")


def _check_version(server_version: str | None) -> CheckResult:
    if server_version is None:
        return CheckResult(
            "version", True, f"sdk {sdk_version}; server unknown (unreachable)"
        )
    if server_version == sdk_version:
        return CheckResult(
            "version", True, f"sdk {sdk_version} == server {server_version}"
        )
    return CheckResult(
        "version",
        True,
        f"sdk {sdk_version} != server {server_version} (skew — informational only)",
    )


def run_doctor(
    *,
    endpoint: str,
    spool_root: Path = _DEFAULT_SPOOL_ROOT,
    out: TextIO = sys.stdout,
    client: httpx.Client | None = None,
) -> int:
    """Run all checks, print a PASS/WARN/FAIL line per check, return an
    exit code (0 if nothing is a hard failure)."""
    connectivity, server_version = _check_connectivity(endpoint, client)
    checks = [connectivity, _check_spool(spool_root), _check_version(server_version)]

    for check in checks:
        marker = "PASS" if check.ok else "FAIL"
        print(f"[{marker}] {check.name}: {check.detail}", file=out)

    return 0 if all(check.ok for check in checks) else 1
