"""Process-wide SDK runtime (TRZ-P2-03): the singleton Recorder — and the
Shipper/DiskSpool it owns — constructed once by ``trazo.init()``.

Kept separate from ``trazo.core.context`` (which owns config + contextvars
only): this module owns the heavier runtime objects (background thread,
HTTP client, disk spool) so tests exercising plain config resolution never
need to spin one up.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from trazo.core.recorder import Recorder
from trazo.core.shipper import Shipper
from trazo.core.spool import DiskSpool, max_bytes_from_env
from trazo.errors import NotInitializedError

_recorder: Recorder | None = None


def init_recorder(
    *,
    endpoint: str,
    api_key: str,
    spool_root: Path | None = None,
    client: httpx.Client | None = None,
) -> Recorder:
    """Build and install the process-wide Recorder. ``client``/``spool_root``
    are test-only injection points; production callers never set them."""
    global _recorder
    spool = DiskSpool(
        spool_root or Path(".trazo/spool"), max_bytes=max_bytes_from_env()
    )
    shipper = Shipper(endpoint=endpoint, api_key=api_key, spool=spool, client=client)
    _recorder = Recorder(shipper=shipper)
    return _recorder


def get_recorder() -> Recorder:
    if _recorder is None:
        raise NotInitializedError()
    return _recorder


def is_initialized() -> bool:
    return _recorder is not None


def _reset_runtime_for_tests() -> None:
    """Test-only: shut down and clear the global recorder between tests."""
    global _recorder
    if _recorder is not None:
        _recorder.shutdown(timeout=1.0)
    _recorder = None


def _install_recorder_for_tests(recorder: Recorder) -> None:
    """Test-only: install an already-built Recorder (e.g. one wired to a
    fake Shipper) without going through init_recorder's own Shipper/
    DiskSpool construction."""
    global _recorder
    _recorder = recorder
