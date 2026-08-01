"""Process-wide SDK runtime (TRZ-P2-03): the singleton Recorder — and the
Shipper/DiskSpool it owns — constructed once by ``trazo.init()``.

Kept separate from ``trazo.core.context`` (which owns config + contextvars
only): this module owns the heavier runtime objects (background thread,
HTTP client, disk spool) so tests exercising plain config resolution never
need to spin one up.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx

from trazo.core.policy import PolicyHook
from trazo.core.recorder import Recorder
from trazo.core.shipper import Shipper
from trazo.core.spool import DiskSpool, max_bytes_from_env
from trazo.errors import NotInitializedError

_recorder: Recorder | None = None
_policy_hook: PolicyHook | None = None


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


def init_policy_hook(
    *, endpoint: str, api_key: str, client: httpx.Client | None = None
) -> PolicyHook:
    """Build and install the process-wide PolicyHook (TRZ-P6-04). ``client``
    is a test-only injection point; production callers never set it."""
    global _policy_hook
    _policy_hook = PolicyHook(endpoint=endpoint, api_key=api_key, client=client)
    return _policy_hook


def get_policy_hook() -> PolicyHook:
    if _policy_hook is None:
        raise NotInitializedError()
    return _policy_hook


def try_get_policy_hook() -> PolicyHook | None:
    """``get_policy_hook()``, tolerant of ``trazo.init()`` never having
    been called — every adapter/decorator call site that governs an
    action needs this same tolerance (tests that construct things with
    an explicit ``recorder=`` override and no ``trazo.init()`` call at
    all must not break for a feature, TRZ-P6-04, that's a no-op by
    default anyway — ``PolicyHook``'s own default mode is ``off``)."""
    try:
        return get_policy_hook()
    except NotInitializedError:
        return None


def is_initialized() -> bool:
    return _recorder is not None


@contextmanager
def replay_recorder_scope(recorder: Recorder) -> Iterator[None]:
    """Temporarily install ``recorder`` as the process-wide recorder,
    restoring whatever was installed before on exit (TRZ-P4-05) — used by
    ``trazo.replay`` so running a replay session never permanently
    clobbers a real ``trazo.init()``'d RECORD-mode recorder, if one
    exists in this process."""
    global _recorder
    previous = _recorder
    _recorder = recorder
    try:
        yield
    finally:
        _recorder = previous


def _reset_runtime_for_tests() -> None:
    """Test-only: shut down and clear the global recorder/policy hook
    between tests."""
    global _recorder, _policy_hook
    if _recorder is not None:
        _recorder.shutdown(timeout=1.0)
    _recorder = None
    if _policy_hook is not None:
        _policy_hook.close()
    _policy_hook = None


def _install_recorder_for_tests(recorder: Recorder) -> None:
    """Test-only: install an already-built Recorder (e.g. one wired to a
    fake Shipper) without going through init_recorder's own Shipper/
    DiskSpool construction."""
    global _recorder
    _recorder = recorder


def _install_policy_hook_for_tests(policy_hook: PolicyHook) -> None:
    """Test-only: install an already-built PolicyHook (e.g. one wired to a
    mocked httpx transport) without going through init_policy_hook's own
    construction, so decorator/adapter call sites see it via
    try_get_policy_hook()/get_policy_hook() exactly as in production."""
    global _policy_hook
    _policy_hook = policy_hook
