"""Trazo SDK: record, replay, and govern multi-agent AI systems.

Public API surface (SDK.md §1) is deliberately tiny; this module is the
only place users import from directly.
"""

from trazo.core import context as _context
from trazo.core import runtime as _runtime
from trazo.core.shipper import RECOMMENDED_SHUTDOWN_TIMEOUT_SECONDS as _SHUTDOWN_TIMEOUT
from trazo.decorators import (
    trace_llm,
    trace_memory_read,
    trace_memory_write,
    trace_tool,
)

__version__ = "0.1.0.dev0"


def init(
    *, project: str, endpoint: str = "http://localhost:8420", api_key: str | None = None
) -> None:
    """Configure the SDK and start its background recorder (SDK.md §1).

    Call once, at process startup: resolves config (env fallback for
    ``api_key``), then builds the process-wide Recorder — its Shipper
    background thread and DiskSpool — that every adapter's
    ``Recorder.boundary`` call goes through.
    """
    _context.init(project=project, endpoint=endpoint, api_key=api_key)
    config = _context.get_config()
    _runtime.init_recorder(endpoint=config.endpoint, api_key=config.api_key)


def shutdown(*, timeout: float = _SHUTDOWN_TIMEOUT) -> None:
    """Flush every buffered event and stop the background Shipper thread.

    ``atexit`` does this too (``Recorder.shutdown``'s docstring), but that
    hook is not reliable for a short-lived process (a CLI invocation, a
    demo script, a test): call this explicitly right before exiting for a
    deterministic flush — confirmed empirically while building the
    research-assistant demo (TRZ-P3-02), where relying on atexit alone
    left most of a run's events stuck in the queue when the process exited
    a few hundred milliseconds after the graph finished.

    The default timeout (see ``RECOMMENDED_SHUTDOWN_TIMEOUT_SECONDS``) is
    long enough for one flush cycle's worst case against an unreachable
    endpoint — draining a previously-failed batch, then posting the new
    one, each up to the Shipper's own POST timeout — found empirically
    (TRZ-P3-03) after a *shorter* explicit timeout silently dropped a
    demo's largest batch when the process exited mid-POST.
    """
    _runtime.get_recorder().shutdown(timeout=timeout)


__all__ = [
    "__version__",
    "init",
    "shutdown",
    "trace_llm",
    "trace_memory_read",
    "trace_memory_write",
    "trace_tool",
]
