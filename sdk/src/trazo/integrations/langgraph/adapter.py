"""LangGraph adapter: ``instrument(graph)`` (TRZ-P2-04).

Wraps a compiled LangGraph graph so run/step lifecycle events and LLM/tool
boundaries are captured through Recorder. See ``callback_handler.py``'s
docstring for exactly how (and why) step/LLM/tool boundaries are derived
from LangChain's callback system alone.

Phase 2 scope is ``.invoke()`` only (TASKS/PHASE_2.md's task list);
instrumenting ``.stream()``/``.astream()`` pass-through is later work.
"""

from __future__ import annotations

import time
from typing import Any

import langgraph

from trazo import __version__ as _SDK_VERSION
from trazo.core.context import get_config, run_scope
from trazo.core.policy import PolicyHook
from trazo.core.recorder import Recorder
from trazo.core.runtime import get_policy_hook, get_recorder
from trazo.core.serialization import to_json_safe
from trazo.errors import NotInitializedError
from trazo.integrations.langgraph.callback_handler import TrazoCallbackHandler


def _try_get_policy_hook() -> PolicyHook | None:
    """``get_policy_hook()``, tolerant of ``trazo.init()`` never having
    been called — every existing test constructs ``InstrumentedGraph``
    with an explicit ``recorder=`` override and no ``trazo.init()`` call
    at all; requiring a policy hook unconditionally would break every one
    of them for a feature (TRZ-P6-04) that's a no-op by default anyway
    (``PolicyHook``'s own default mode is ``off``)."""
    try:
        return get_policy_hook()
    except NotInitializedError:
        return None


_LANGGRAPH_VERSION = getattr(langgraph, "__version__", "unknown")


class InstrumentedGraph:
    """Wraps a compiled LangGraph graph; call ``.invoke(...)`` exactly like
    the original. Any other attribute (``get_graph``, ``name``, ...) passes
    straight through to the wrapped graph, uninstrumented."""

    def __init__(
        self,
        graph: Any,
        *,
        recorder: Recorder | None = None,
        policy_hook: PolicyHook | None = None,
        tags: dict[str, Any] | None = None,
    ) -> None:
        self._graph = graph
        self._recorder_override = recorder
        self._policy_hook_override = policy_hook
        self._tags = tags or {}
        self.last_run_id: str | None = None

    def invoke(
        self, input: dict[str, Any], config: dict[str, Any] | None = None
    ) -> Any:
        recorder = self._recorder_override or get_recorder()
        policy_hook = self._policy_hook_override or _try_get_policy_hook()
        run_config = dict(config or {})
        handler = TrazoCallbackHandler(recorder, policy_hook=policy_hook)
        run_config["callbacks"] = [*run_config.get("callbacks", []), handler]

        with run_scope(get_config().project) as run_ctx:
            self.last_run_id = run_ctx.run_id
            start_time = time.monotonic()
            recorder.emit(
                "run.started",
                {
                    "framework": "langgraph",
                    "framework_version": _LANGGRAPH_VERSION,
                    "sdk_version": _SDK_VERSION,
                    "entry_input": to_json_safe(input),
                    "tags": self._tags,
                },
            )
            status = "ok"
            try:
                return self._graph.invoke(input, config=run_config)
            except Exception:
                status = "error"
                raise
            finally:
                duration_ms = (time.monotonic() - start_time) * 1000
                totals = run_ctx.totals
                recorder.emit(
                    "run.finished",
                    {
                        "status": status,
                        "totals": {
                            "events": (
                                2
                                + handler.step_count
                                + totals.llm_calls
                                + totals.tool_calls
                            ),
                            "llm_calls": totals.llm_calls,
                            "tool_calls": totals.tool_calls,
                            "cost_usd": totals.cost_usd,
                            "tokens_in": totals.tokens_in,
                            "tokens_out": totals.tokens_out,
                            "duration_ms": duration_ms,
                        },
                    },
                )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._graph, name)


def instrument(
    graph: Any,
    *,
    recorder: Recorder | None = None,
    policy_hook: PolicyHook | None = None,
    tags: dict[str, Any] | None = None,
) -> InstrumentedGraph:
    """SDK.md §1: ``traced_graph = instrument(graph)``.

    ``graph`` is a compiled LangGraph graph (``StateGraph(...).compile()``).
    ``recorder``/``policy_hook`` are test-only injection points;
    production callers rely on the process-wide instances installed by
    ``trazo.init()``. ``tags`` is recorded verbatim on ``run.started``
    (e.g. the chaos harness's ``injected_failure`` ground truth, TRZ-P5-01).
    """
    return InstrumentedGraph(
        graph, recorder=recorder, policy_hook=policy_hook, tags=tags
    )
