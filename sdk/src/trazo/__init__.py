"""Trazo SDK: record, replay, and govern multi-agent AI systems.

Public API surface (SDK.md §1) is deliberately tiny; this module is the
only place users import from directly.
"""

from trazo.core import context as _context
from trazo.core import runtime as _runtime
from trazo.decorators import trace_llm, trace_tool

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


__all__ = ["__version__", "init", "trace_llm", "trace_tool"]
