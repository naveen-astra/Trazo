"""``@trace_tool`` / ``@trace_llm`` / ``@trace_memory_read`` /
``@trace_memory_write`` — the custom-agent escape hatch (TRZ-P2-05;
memory variants added in TRZ-P3-02 since a demo needing "memory events
present" — IMPLEMENTATION_PLAN.md's lane table restricts `demos/` to the
SDK's public API only, and no adapter auto-captures memory operations
(EVENTS.md §2.3's `memory.read`/`memory.write` — SDK.md §2's coverage
table: "yes if framework exposes it", and none of Phase 2/3's adapters
do) — needed a public way to emit them without reaching into
`trazo.core`).

For code with no framework adapter (or a specific call an adapter doesn't
catch): wraps a plain function so every call goes through
``Recorder.boundary`` automatically, exactly like an adapter would (SDK.md
§1). All four decorators bind the call's positional/keyword arguments to
the wrapped function's parameter names (via ``inspect.signature(...)
.bind``) so the recorded ``args``/``messages_in``/``query``/``value`` are
real values, not an opaque positional tuple.
"""

from __future__ import annotations

import functools
import inspect
import time
from collections.abc import Callable
from typing import Any, TypeVar

from trazo.core.runtime import get_recorder, try_get_policy_hook

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

            # TRZ-P6-04/ADR-006, same governed-action check the LangGraph
            # adapter's on_tool_start does before dispatching to a native
            # framework tool -- this decorator is the *other* path a
            # tool.call reaches Recorder.boundary through (SDK.md §1's
            # "escape hatch for custom agents / un-adapted boundaries"),
            # and until this fix it silently skipped policy checking
            # entirely: confirmed live, a demo using only this decorator
            # for its tools ran $108 over a $5 cost cap in enforce mode
            # with zero policy decisions ever made, because nothing here
            # ever called PolicyHook.check(). Raising PolicyDenied before
            # execute() is what makes "the blocked call never executes"
            # true for this path too -- it propagates straight out of
            # wrapper(), no callback-exception-swallowing concern here
            # (that's a LangChain-specific problem the adapter's own
            # raise_error property works around; a plain function call
            # has no equivalent to work around).
            policy_hook = try_get_policy_hook()
            if policy_hook is not None:
                policy_hook.check(
                    kind="tool.call",
                    tool_name=tool_name,
                    args=call_args,
                    side_effect_class=side_effect_class,
                )

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
    In RECORD mode, the caller gets back exactly what the function
    returned, unchanged. In REPLAY mode ``fn`` is never called (TRZ-P4-02:
    that's the entire point), so there is no original return value to
    reproduce verbatim — the caller gets back the recorded/substituted
    ``{"response", "tokens_in", "tokens_out", "cost_usd", "latency_ms"}``
    dict instead (matching the common case of a dict-shaped return; a
    function that returns a bare value in RECORD mode gets a dict back
    in REPLAY mode instead of its original bare shape — a documented,
    narrow limitation of this escape hatch, not of framework adapters).
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

            merged = recorder.boundary(
                "llm.call",
                {
                    "provider": provider,
                    "model": model,
                    "params": {},
                    "messages_in": call_args,
                },
                execute,
            )
            # RECORD mode: execute() ran, so raw_result_holder has fn's
            # exact original return value — return that, unchanged. REPLAY
            # mode never calls execute(), so it's absent; fall back to the
            # recorded/substituted dict (see docstring for the tradeoff).
            if "value" in raw_result_holder:
                return raw_result_holder["value"]
            return merged

        return wrapper  # type: ignore[return-value]

    return decorator


def trace_memory_read(*, store: str = "vector") -> Callable[[F], F]:
    """Wrap a plain function as a traced ``memory.read`` boundary.

    The wrapped function's bound arguments supply ``query`` (its ``query``
    parameter if present, otherwise the whole bound-argument dict) and
    ``k`` (its ``k`` parameter, if present). The function's return value
    becomes ``results`` and is returned to the caller unchanged.
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            recorder = get_recorder()
            call_args = _bind_args(fn, args, kwargs)
            query = call_args.get("query", call_args)
            k = call_args.get("k")
            start = time.monotonic()

            def execute() -> dict[str, Any]:
                results = fn(*args, **kwargs)
                latency_ms = (time.monotonic() - start) * 1000
                return {"results": results, "latency_ms": latency_ms}

            merged = recorder.boundary(
                "memory.read",
                {"store": store, "query": query, "k": k},
                execute,
            )
            return merged["results"]

        return wrapper  # type: ignore[return-value]

    return decorator


def trace_memory_write(*, store: str = "vector") -> Callable[[F], F]:
    """Wrap a plain function as a traced ``memory.write`` boundary.

    The wrapped function's bound arguments supply ``key_or_ns`` (its
    ``key_or_ns`` or ``key`` parameter, if present, else ``"default"``)
    and ``value`` (its ``value`` parameter if present, otherwise the whole
    bound-argument dict). In RECORD mode the function's return value is
    returned to the caller unchanged. In REPLAY mode ``fn`` is never
    called (TRZ-P4-02), and ``memory.write``'s recorded payload carries no
    return-value field to reproduce (EVENTS.md §2.3), so the caller gets
    ``None`` — matching every real write function's actual return value.
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            recorder = get_recorder()
            call_args = _bind_args(fn, args, kwargs)
            key_or_ns = call_args.get("key_or_ns") or call_args.get("key") or "default"
            value = call_args.get("value", call_args)
            start = time.monotonic()
            raw_result_holder: dict[str, Any] = {}

            def execute() -> dict[str, Any]:
                raw_result_holder["value"] = fn(*args, **kwargs)
                latency_ms = (time.monotonic() - start) * 1000
                return {"latency_ms": latency_ms}

            recorder.boundary(
                "memory.write",
                {"store": store, "key_or_ns": key_or_ns, "value": value},
                execute,
            )
            return raw_result_holder.get("value")

        return wrapper  # type: ignore[return-value]

    return decorator
