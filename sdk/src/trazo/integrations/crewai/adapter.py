"""CrewAI adapter: ``instrument(crew)`` (TRZ-P3-01).

Wraps a CrewAI ``Crew`` so run/step lifecycle events and LLM/tool/memory/
delegation boundaries are captured through Recorder. See ``listener.py``'s
docstring for exactly how (and why) those boundaries are derived from
CrewAI's event bus alone.

Unlike the LangGraph adapter, run.started/run.finished aren't derived from
any CrewAI event (there's no single "kickoff" event pair as clean as
LangGraph's node middleware) — this wraps ``Crew.kickoff()`` directly,
same shape as ``InstrumentedGraph.invoke()``.

Policy enforcement (TRZ-P6-04) governs each tool on the crew's agents and
tasks: for the duration of ``kickoff()`` every tool's ``_run``/``_arun`` is
replaced by a wrapper that calls ``PolicyHook.check()`` first, so a denied
call never reaches the tool's body. CrewAI catches tool exceptions and hands
them back to the agent as text, so a ``PolicyDenied`` raised in the wrapper
would otherwise vanish; the adapter records it and re-raises it from
``kickoff()`` once the crew stops, matching the LangGraph adapter's contract
that ``PolicyDenied`` propagates to the caller.

Phase 3 scope is ``Process.sequential`` (TASKS/PHASE_3.md's toy-crew
boundary-coverage audit); ``Process.hierarchical`` isn't specifically
exercised yet.
"""

from __future__ import annotations

import contextvars
import functools
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import crewai
from crewai.events.event_bus import crewai_event_bus

from trazo import __version__ as _SDK_VERSION
from trazo.core.context import get_config, run_scope
from trazo.core.recorder import Recorder
from trazo.core.runtime import get_recorder, try_get_policy_hook
from trazo.core.serialization import to_json_safe
from trazo.errors import PolicyDenied
from trazo.integrations.crewai.listener import CrewEventCapture

if TYPE_CHECKING:
    from crewai import Crew
    from crewai.tools import BaseTool

    from trazo.core.policy import PolicyHook

_CREWAI_VERSION = getattr(crewai, "__version__", "unknown")

# Same conservative default as the LangGraph adapter; see README.
_SIDE_EFFECT_CLASS = "external"


def _crew_tools(crew: Crew) -> list[BaseTool]:
    """Every distinct tool on the crew's agents and tasks. Tools CrewAI
    builds for itself at task time (delegation) are not here, and are
    recorded as agent.message rather than tool.call anyway."""
    seen: dict[int, BaseTool] = {}
    for owner in [*(crew.agents or []), *(crew.tasks or [])]:
        for tool in getattr(owner, "tools", None) or []:
            seen.setdefault(id(tool), tool)
    return list(seen.values())


def _policy_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    safe = to_json_safe({**kwargs, **({"args": list(args)} if args else {})})
    return safe if isinstance(safe, dict) else {}


@contextmanager
def _governed_tools(
    crew: Crew, policy_hook: PolicyHook, denials: list[PolicyDenied]
) -> Iterator[None]:
    """Puts a policy check in front of every crew tool until exit.

    The wrapper goes on the instance, shadowing the class's ``_run``: CrewAI
    resolves ``self._run`` when it builds each task's executor and when a
    tool runs, both inside ``kickoff()``. The check runs in a copy of the
    kickoff's context so it finds the active run even when CrewAI runs the
    tool on another thread (``async_execution`` tasks)."""
    run_context = contextvars.copy_context()
    patched: list[tuple[BaseTool, str]] = []

    def check(tool: BaseTool, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        try:
            run_context.copy().run(
                policy_hook.check,
                kind="tool.call",
                tool_name=tool.name,
                args=_policy_args(args, kwargs),
                side_effect_class=_SIDE_EFFECT_CLASS,
            )
        except PolicyDenied as exc:
            denials.append(exc)
            raise

    def govern_sync(tool: BaseTool, original: Any) -> Any:
        @functools.wraps(original)
        def run(*args: Any, **kwargs: Any) -> Any:
            check(tool, args, kwargs)
            return original(*args, **kwargs)

        return run

    def govern_async(tool: BaseTool, original: Any) -> Any:
        @functools.wraps(original)
        async def arun(*args: Any, **kwargs: Any) -> Any:
            check(tool, args, kwargs)
            return await original(*args, **kwargs)

        return arun

    try:
        for tool in _crew_tools(crew):
            for name, govern in (("_run", govern_sync), ("_arun", govern_async)):
                if name in tool.__dict__ or not callable(getattr(tool, name, None)):
                    continue
                # object.__setattr__: pydantic refuses unknown attributes.
                object.__setattr__(tool, name, govern(tool, getattr(tool, name)))
                patched.append((tool, name))
        yield
    finally:
        for tool, name in patched:
            tool.__dict__.pop(name, None)


class InstrumentedCrew:
    """Wraps a CrewAI ``Crew``; call ``.kickoff(...)`` exactly like the
    original. Any other attribute passes straight through to the wrapped
    crew, uninstrumented."""

    def __init__(
        self,
        crew: Crew,
        *,
        recorder: Recorder | None = None,
        policy_hook: PolicyHook | None = None,
        tags: dict[str, Any] | None = None,
    ) -> None:
        self._crew = crew
        self._recorder_override = recorder
        self._policy_hook_override = policy_hook
        self._tags = tags or {}
        self.last_run_id: str | None = None

    def kickoff(self, inputs: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        recorder = self._recorder_override or get_recorder()
        policy_hook = self._policy_hook_override or try_get_policy_hook()
        capture = CrewEventCapture(recorder)
        denials: list[PolicyDenied] = []

        with run_scope(get_config().project) as run_ctx:
            self.last_run_id = run_ctx.run_id
            start_time = time.monotonic()
            recorder.emit(
                "run.started",
                {
                    "framework": "crewai",
                    "framework_version": _CREWAI_VERSION,
                    "sdk_version": _SDK_VERSION,
                    "entry_input": to_json_safe(inputs or {}),
                    "tags": self._tags,
                },
            )
            status = "ok"
            capture.register()
            try:
                if policy_hook is None:
                    return self._crew.kickoff(inputs=inputs, **kwargs)
                with _governed_tools(self._crew, policy_hook, denials):
                    result = self._crew.kickoff(inputs=inputs, **kwargs)
                if denials:
                    # The blocked tool never ran; CrewAI only told the agent.
                    raise denials[0]
                return result
            except Exception:
                status = "error"
                raise
            finally:
                # crewai_event_bus.emit() is fire-and-forget onto a
                # 10-worker thread pool with no cross-event ordering
                # guarantee (see listener.py's module docstring for the
                # empirically-discovered race this produced). flush() —
                # CrewAI's own documented "wait for all pending handlers"
                # mechanism — guarantees every event this run produced has
                # reached capture's buffer before process() sorts and
                # replays them in true (emission_sequence) order.
                crewai_event_bus.flush()
                capture.unregister()
                capture.process()
                duration_ms = (time.monotonic() - start_time) * 1000
                totals = run_ctx.totals
                recorder.emit(
                    "run.finished",
                    {
                        "status": status,
                        "totals": {
                            # +1 for this run.finished itself: the tally is
                            # read before the event is emitted, so it counts
                            # everything up to but not including it.
                            "events": totals.events + 1,
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
        return getattr(self._crew, name)


def instrument(
    crew: Crew,
    *,
    recorder: Recorder | None = None,
    policy_hook: PolicyHook | None = None,
    tags: dict[str, Any] | None = None,
) -> InstrumentedCrew:
    """SDK.md §1: ``traced_crew = instrument(crew)``.

    ``crew`` is a CrewAI ``Crew`` instance. ``recorder``/``policy_hook``
    are test-only injection points; production callers rely on the
    process-wide ones installed by ``trazo.init()``. ``tags`` is recorded verbatim on
    ``run.started`` (e.g. the chaos harness's ``injected_failure`` ground
    truth, TRZ-P5-01).
    """
    return InstrumentedCrew(crew, recorder=recorder, policy_hook=policy_hook, tags=tags)
