"""``@trace_tool`` / ``@trace_llm`` — the custom-agent escape hatch (TRZ-P2-05).

For code with no framework adapter (or a specific call an adapter doesn't
catch): wraps a plain function so every call goes through
``Recorder.boundary`` automatically, exactly like an adapter would (SDK.md
§1). Both decorators bind the call's positional/keyword arguments to the
wrapped function's parameter names (via ``inspect.signature(...).bind``)
so the recorded ``args``/``messages_in`` are a real dict, not an opaque
positional tuple.
"""

from __future__ import annotations

import functools
import inspect
import time
from collections.abc import Callable
from typing import Any, TypeVar

from trazo.core.runtime import get_recorder

F = TypeVar("F", bound=Callable[..., Any])


def _bind_args(
    fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any]:
    try:
        bound = inspect.signature(fn).bind(*args, **kwargs)
        bound.apply_defaults()
        return dict(bound.arguments)
    except TypeError:
        # fn's signature couldn't bind the given call (e.g. bare *args) —
        # fall back to a best-effort positional/keyword representation
        # rather than raising from inside instrumentation.
        return {"args": list(args), "kwargs": kwargs}


def trace_tool(
    *, side_effect_class: str = "external", name: str | None = None
) -> Callable[[F], F]:
    """Wrap a plain function as a traced ``tool.call`` boundary.

    ``side_effect_class``: ``read`` | ``write`` | ``external``
    (EVENTS.md §2.3) — defaults to the conservative ``external`` (policy
    defaults are stricter for write/external).
    """

    def decorator(fn: F) -> F:
        tool_name = name or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            recorder = get_recorder()
            call_args = _bind_args(fn, args, kwargs)
            start = time.monotonic()

            def execute() -> dict[str, Any]:
                result = fn(*args, **kwargs)
                latency_ms = (time.monotonic() - start) * 1000
                return {"result": result, "status": "ok", "latency_ms": latency_ms}

            merged = recorder.boundary(
                "tool.call",
                {
                    "tool_name": tool_name,
                    "args": call_args,
                    "side_effect_class": side_effect_class,
                },
                execute,
            )
            return merged["result"]

        return wrapper  # type: ignore[return-value]

    return decorator


def trace_llm(*, provider: str, model: str) -> Callable[[F], F]:
    """Wrap a plain function as a traced ``llm.call`` boundary.

    The wrapped function's call arguments become ``messages_in``. If the
    function returns a dict containing a ``response`` key, its
    ``tokens_in``/``tokens_out``/``cost_usd`` are used too (0/0.0 if
    absent); otherwise the whole return value is treated as ``response``.
    Either way, the caller gets back exactly what the function returned,
    unchanged.
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            recorder = get_recorder()
            call_args = _bind_args(fn, args, kwargs)
            start = time.monotonic()
            raw_result_holder: dict[str, Any] = {}

            def execute() -> dict[str, Any]:
                raw_result = fn(*args, **kwargs)
                raw_result_holder["value"] = raw_result
                latency_ms = (time.monotonic() - start) * 1000
                if isinstance(raw_result, dict) and "response" in raw_result:
                    return {
                        "response": raw_result["response"],
                        "tokens_in": raw_result.get("tokens_in", 0),
                        "tokens_out": raw_result.get("tokens_out", 0),
                        "cost_usd": raw_result.get("cost_usd", 0.0),
                        "latency_ms": latency_ms,
                    }
                return {
                    "response": raw_result,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "cost_usd": 0.0,
                    "latency_ms": latency_ms,
                }

            recorder.boundary(
                "llm.call",
                {
                    "provider": provider,
                    "model": model,
                    "params": {},
                    "messages_in": call_args,
                },
                execute,
            )
            return raw_result_holder["value"]

        return wrapper  # type: ignore[return-value]

    return decorator
