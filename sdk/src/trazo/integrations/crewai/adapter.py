"""CrewAI adapter: ``instrument(crew)`` (TRZ-P3-01).

Wraps a CrewAI ``Crew`` so run/step lifecycle events and LLM/tool/memory/
delegation boundaries are captured through Recorder. See ``listener.py``'s
docstring for exactly how (and why) those boundaries are derived from
CrewAI's event bus alone.

Unlike the LangGraph adapter, run.started/run.finished aren't derived from
any CrewAI event (there's no single "kickoff" event pair as clean as
LangGraph's node middleware) — this wraps ``Crew.kickoff()`` directly,
same shape as ``InstrumentedGraph.invoke()``.

Phase 3 scope is ``Process.sequential`` (TASKS/PHASE_3.md's toy-crew
boundary-coverage audit); ``Process.hierarchical`` isn't specifically
exercised yet.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import crewai
from crewai.events.event_bus import crewai_event_bus

from trazo import __version__ as _SDK_VERSION
from trazo.core.context import get_config, run_scope
from trazo.core.recorder import Recorder
from trazo.core.runtime import get_recorder
from trazo.core.serialization import to_json_safe
from trazo.integrations.crewai.listener import CrewEventCapture

if TYPE_CHECKING:
    from crewai import Crew

_CREWAI_VERSION = getattr(crewai, "__version__", "unknown")


class InstrumentedCrew:
    """Wraps a CrewAI ``Crew``; call ``.kickoff(...)`` exactly like the
    original. Any other attribute passes straight through to the wrapped
    crew, uninstrumented."""

    def __init__(self, crew: Crew, *, recorder: Recorder | None = None) -> None:
        self._crew = crew
        self._recorder_override = recorder
        self.last_run_id: str | None = None

    def kickoff(self, inputs: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        recorder = self._recorder_override or get_recorder()
        capture = CrewEventCapture(recorder)

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
                    "tags": {},
                },
            )
            status = "ok"
            capture.register()
            try:
                return self._crew.kickoff(inputs=inputs, **kwargs)
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
                recorder.emit(
                    "run.finished",
                    {
                        "status": status,
                        "totals": {
                            "events": 2
                            + capture.event_count,  # +2 for run.started/finished
                            "llm_calls": capture.llm_call_count,
                            "tool_calls": capture.tool_call_count,
                            "cost_usd": 0.0,  # needs a pricing table; known gap
                            "tokens_in": capture.tokens_in_total,
                            "tokens_out": capture.tokens_out_total,
                            "duration_ms": duration_ms,
                        },
                    },
                )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._crew, name)


def instrument(crew: Crew, *, recorder: Recorder | None = None) -> InstrumentedCrew:
    """SDK.md §1: ``traced_crew = instrument(crew)``.

    ``crew`` is a CrewAI ``Crew`` instance. ``recorder`` is a test-only
    injection point; production callers rely on the process-wide recorder
    installed by ``trazo.init()``.
    """
    return InstrumentedCrew(crew, recorder=recorder)
