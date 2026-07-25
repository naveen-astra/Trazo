"""Maps CrewAI's event bus (``crewai.events``) onto Recorder calls
(TRZ-P3-01) — SDK.md §3's CrewAI contract: task execution = steps,
agent-to-agent delegation = ``agent.message``, tool wrapping via CrewAI's
own tool-usage events.

Design notes (verified empirically against crewai 1.15.6, not assumed):

- Unlike LangChain's callback system, CrewAI's ``crewai_event_bus`` is a
  process-wide singleton with explicit ``on``/``off`` registration — every
  event already carries ``task_id``/``task_name``/``agent_id``/
  ``agent_role`` directly (set by the base event classes), so unlike the
  LangGraph adapter there's no need to walk a parent-run-id chain to find
  the enclosing step: a dict keyed by ``task_id`` is enough.
- ``LLMCallStartedEvent``/``LLMCallCompletedEvent`` share a ``call_id``,
  which is the correlation key for pairing them into one ``llm.call``.
- ``ToolUsageStartedEvent``/``ToolUsageFinishedEvent`` carry no shared id,
  but CrewAI's agent executor runs one tool call at a time per task (both
  the native-function-calling and classic ReAct-text-parsing paths are
  synchronous) — a FIFO queue keyed by ``task_id`` pairs them correctly.
- Delegation and "ask a coworker" are *not* separate event types — CrewAI
  implements both as tools (``Delegate work to coworker`` /
  ``Ask question to coworker``, see ``crewai.tools.agent_tools``), so
  those two tool names are special-cased into ``agent.message`` instead of
  ``tool.call``.
- On a failed LLM/tool call, no boundary event is recorded — same
  reasoning as the LangGraph adapter's ``on_llm_error``/``on_tool_error``:
  ``Recorder.boundary`` has no schema-valid way to represent a failed call
  without a response.
- **Critical, empirically-discovered ordering hazard**: ``crewai_event_bus
  .emit()`` is fire-and-forget — it submits each event to a 10-worker
  ``ThreadPoolExecutor`` and returns immediately without waiting, and
  CrewAI's own emitters never wait on the returned Future either. With
  more than one worker, handler *execution* order does not match emission
  order (confirmed by a flaky boundary-coverage test: the first llm.call
  of a run occasionally landed after its own tool.call). The only field
  that reliably reflects true emission order is ``event.emission_sequence``
  (assigned synchronously, on the emitting thread, before the event is
  handed to the pool — see ``crewai.events.event_bus._prepare_event``).
  So this listener does not process events as they arrive: every handler
  just buffers its event; ``process()`` sorts the buffer by
  ``emission_sequence`` and replays it through the real per-kind handling
  in one single-threaded pass, called only after ``InstrumentedCrew
  .kickoff()`` has called ``crewai_event_bus.flush()`` (CrewAI's own
  documented "wait for all pending handlers" mechanism) — so every event
  the run produced is guaranteed to be in the buffer, in the right order,
  before anything reaches ``Recorder``.
- Scope: ``Process.sequential`` toy crews (TRZ-P3-01's own boundary-
  coverage audit). ``Process.hierarchical`` isn't specifically exercised
  yet — later work, same spirit as the LangGraph adapter's ``.invoke()``-
  only Phase 2 scope note.
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from crewai.events.event_bus import crewai_event_bus
from crewai.events.types.llm_events import (
    LLMCallCompletedEvent,
    LLMCallFailedEvent,
    LLMCallStartedEvent,
)
from crewai.events.types.memory_events import (
    MemoryQueryCompletedEvent,
    MemoryQueryFailedEvent,
    MemoryQueryStartedEvent,
    MemorySaveCompletedEvent,
    MemorySaveFailedEvent,
    MemorySaveStartedEvent,
)
from crewai.events.types.task_events import (
    TaskCompletedEvent,
    TaskFailedEvent,
    TaskStartedEvent,
)
from crewai.events.types.tool_usage_events import (
    ToolUsageErrorEvent,
    ToolUsageFinishedEvent,
    ToolUsageStartedEvent,
)
from crewai.utilities.string_utils import sanitize_tool_name

from trazo.core.context import optional_agent_scope, optional_step_scope
from trazo.core.recorder import Recorder
from trazo.core.serialization import hash_state, to_json_safe
from trazo.core.ulid import new_step_id

if TYPE_CHECKING:
    from collections.abc import Callable

    from crewai.events.base_events import BaseEvent

_UNKNOWN_TASK = "__no_task__"

# CrewAI's agent-executor loop sanitizes every tool name before it reaches
# ToolUsage*Event (crewai.utilities.string_utils.sanitize_tool_name — lowercases
# and underscores, e.g. "Delegate work to coworker" -> "delegate_work_to_coworker";
# verified empirically, not the display name from crewai.tools.agent_tools).
_DELEGATION_TOOL_NAMES = {
    sanitize_tool_name("Delegate work to coworker"): "delegation",
    sanitize_tool_name("Ask question to coworker"): "other",
}

_MODEL_PROVIDER_PREFIXES: dict[str, str] = {
    "gpt-": "openai",
    "o1": "openai",
    "o3": "openai",
    "claude": "anthropic",
    "gemini": "google",
}


def _parse_tool_args(tool_args: dict[str, Any] | str) -> dict[str, Any]:
    """``ToolUsage*Event.tool_args`` is typed ``dict[str, Any] | str`` and
    empirically *is* a raw JSON string on some paths (verified against
    crewai 1.15.6's ReAct executor) — normalize to a dict so ``args``/
    ``content`` payload fields are structured, not a string a consumer
    would need to re-parse."""
    if isinstance(tool_args, dict):
        return tool_args
    try:
        parsed = json.loads(tool_args)
    except (TypeError, ValueError):
        return {"raw": tool_args}
    return parsed if isinstance(parsed, dict) else {"raw": tool_args}


def _infer_provider(model: str | None) -> str:
    """Best-effort provider guess from the model name — CrewAI's LLM
    events don't carry a provider field directly. A known gap (see
    README): wrong for any model name this prefix table doesn't cover."""
    if not model:
        return "unknown"
    lowered = model.lower()
    for prefix, provider in _MODEL_PROVIDER_PREFIXES.items():
        if lowered.startswith(prefix):
            return provider
    return "unknown"


@dataclass
class _StepState:
    step_id: str
    name: str
    index: int


@dataclass
class _PendingLlmCall:
    inputs: dict[str, Any]
    task_id: str
    agent_role: str | None
    started_at: float


@dataclass
class _PendingToolCall:
    inputs: dict[str, Any]
    agent_role: str | None
    started_at: float


@dataclass
class _PendingMemoryOp:
    task_id: str
    agent_role: str | None
    query: str | None = None
    limit: int | None = None


_TRACKED_EVENT_TYPES: tuple[type[BaseEvent], ...] = (
    TaskStartedEvent,
    TaskCompletedEvent,
    TaskFailedEvent,
    LLMCallStartedEvent,
    LLMCallCompletedEvent,
    LLMCallFailedEvent,
    ToolUsageStartedEvent,
    ToolUsageFinishedEvent,
    ToolUsageErrorEvent,
    MemoryQueryStartedEvent,
    MemoryQueryCompletedEvent,
    MemoryQueryFailedEvent,
    MemorySaveStartedEvent,
    MemorySaveCompletedEvent,
    MemorySaveFailedEvent,
)


class CrewEventCapture:
    """One instance per ``InstrumentedCrew.kickoff()`` call: registers
    itself on the global ``crewai_event_bus`` for the call's duration and
    tears the registration down afterward (the bus has no per-call scoping
    of its own — see this module's docstring).

    Call order (owned by ``InstrumentedCrew.kickoff()``): ``register()`` →
    run the crew → ``crewai_event_bus.flush()`` → ``unregister()`` →
    ``process()`` → read the ``*_count``/``*_total`` properties for
    ``run.finished``'s totals.
    """

    def __init__(self, recorder: Recorder) -> None:
        self._recorder = recorder
        self._buffer_lock = threading.Lock()
        self._buffer: list[BaseEvent] = []
        self._handlers: list[tuple[type[BaseEvent], Callable[..., None]]] = []

        self._steps: dict[str, _StepState] = {}
        self._step_index = 0
        self._pending_llm_calls: dict[str, _PendingLlmCall] = {}
        self._pending_tool_calls: dict[str, deque[_PendingToolCall]] = defaultdict(
            deque
        )
        self._pending_memory_queries: deque[_PendingMemoryOp] = deque()
        self._pending_memory_saves: deque[_PendingMemoryOp] = deque()

        self._dispatch: dict[type[BaseEvent], Callable[[Any], None]] = {
            TaskStartedEvent: self._on_task_started,
            TaskCompletedEvent: self._on_task_completed,
            TaskFailedEvent: self._on_task_failed,
            LLMCallStartedEvent: self._on_llm_started,
            LLMCallCompletedEvent: self._on_llm_completed,
            LLMCallFailedEvent: self._on_llm_failed,
            ToolUsageStartedEvent: self._on_tool_started,
            ToolUsageFinishedEvent: self._on_tool_finished,
            ToolUsageErrorEvent: self._on_tool_error,
            MemoryQueryStartedEvent: self._on_memory_query_started,
            MemoryQueryCompletedEvent: self._on_memory_query_completed,
            MemoryQueryFailedEvent: self._on_memory_query_failed,
            MemorySaveStartedEvent: self._on_memory_save_started,
            MemorySaveCompletedEvent: self._on_memory_save_completed,
            MemorySaveFailedEvent: self._on_memory_save_failed,
        }

        self.llm_call_count = 0
        self.tool_call_count = 0
        self.tokens_in_total = 0
        self.tokens_out_total = 0
        self.event_count = 0

    # ---- collection (runs on crewai_event_bus's worker threads) ----

    def register(self) -> None:
        for event_type in _TRACKED_EVENT_TYPES:
            self._on(event_type, self._collect)

    def _on(self, event_type: type[BaseEvent], handler: Callable[..., None]) -> None:
        crewai_event_bus.on(event_type)(handler)
        self._handlers.append((event_type, handler))

    def unregister(self) -> None:
        for event_type, handler in self._handlers:
            crewai_event_bus.off(event_type, handler)
        self._handlers.clear()

    def _collect(self, _source: Any, event: BaseEvent) -> None:
        with self._buffer_lock:
            self._buffer.append(event)

    # ---- replay (single-threaded, call after flush()+unregister()) ----

    def process(self) -> None:
        """Sort the buffer into true emission order and dispatch each
        event through its real handler. Single-threaded by construction
        (called once, after the crew has finished) — none of the
        processing below needs its own locking."""
        self._buffer.sort(key=lambda event: event.emission_sequence or 0)
        for event in self._buffer:
            handler = self._dispatch.get(type(event))
            if handler is not None:
                handler(event)

    # ---- recorder wrappers (every emit counts toward run.finished's totals) ----

    def _emit(self, kind: str, payload: dict[str, Any]) -> None:
        self._recorder.emit(kind, payload)
        self.event_count += 1

    def _boundary(
        self, kind: str, inputs: dict[str, Any], result: dict[str, Any]
    ) -> None:
        self._recorder.boundary(kind, inputs, lambda: result)
        self.event_count += 1

    # ---- step.started / step.finished (task lifecycle) ----

    def _on_task_started(self, event: TaskStartedEvent) -> None:
        task_id = event.task_id or _UNKNOWN_TASK
        step_id = new_step_id()
        name = event.task_name or task_id
        self._steps[task_id] = _StepState(
            step_id=step_id, name=name, index=self._step_index
        )
        self._step_index += 1

        state_hash, snapshot, _unhashed = hash_state({"context": event.context or ""})
        with optional_step_scope(step_id):
            self._emit(
                "step.started",
                {
                    "name": name,
                    "step_index": self._steps[task_id].index,
                    "state_before_hash": state_hash,
                    "state_before": snapshot,
                },
            )

    def _finish_step(
        self, task_id: str | None, *, status: str, state: dict[str, Any]
    ) -> None:
        step = self._steps.pop(task_id or _UNKNOWN_TASK, None)
        if step is None:
            return
        state_hash, snapshot, _unhashed = hash_state(state)
        with optional_step_scope(step.step_id):
            self._emit(
                "step.finished",
                {
                    "status": status,
                    "state_after_hash": state_hash,
                    "state_after": snapshot,
                    "duration_ms": 0.0,  # CrewAI's task events don't carry step latency
                },
            )

    def _on_task_completed(self, event: TaskCompletedEvent) -> None:
        self._finish_step(
            event.task_id, status="ok", state={"output": to_json_safe(event.output)}
        )

    def _on_task_failed(self, event: TaskFailedEvent) -> None:
        self._finish_step(event.task_id, status="error", state={"error": event.error})

    # ---- llm.call ----

    def _on_llm_started(self, event: LLMCallStartedEvent) -> None:
        inputs = {
            "provider": _infer_provider(event.model),
            "model": event.model or "unknown",
            "params": {
                k: v
                for k, v in {
                    "temperature": event.temperature,
                    "top_p": event.top_p,
                    "max_tokens": event.max_tokens,
                }.items()
                if v is not None
            },
            "messages_in": to_json_safe(event.messages),
        }
        self._pending_llm_calls[event.call_id] = _PendingLlmCall(
            inputs=inputs,
            task_id=event.task_id or _UNKNOWN_TASK,
            agent_role=event.agent_role,
            started_at=time.monotonic(),
        )

    def _on_llm_completed(self, event: LLMCallCompletedEvent) -> None:
        pending = self._pending_llm_calls.pop(event.call_id, None)
        if pending is None:
            return
        usage = event.usage or {}
        tokens_in = int(usage.get("prompt_tokens", 0) or 0)
        tokens_out = int(usage.get("completion_tokens", 0) or 0)
        self.tokens_in_total += tokens_in
        self.tokens_out_total += tokens_out
        self.llm_call_count += 1

        result = {
            "response": to_json_safe(event.response),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": 0.0,  # needs a pricing table; known gap (see LangGraph adapter)
            "latency_ms": (time.monotonic() - pending.started_at) * 1000,
        }
        step = self._steps.get(pending.task_id)
        step_id = step.step_id if step is not None else None
        with optional_step_scope(step_id), optional_agent_scope(pending.agent_role):
            self._boundary("llm.call", pending.inputs, result)

    def _on_llm_failed(self, event: LLMCallFailedEvent) -> None:
        self._pending_llm_calls.pop(
            event.call_id, None
        )  # dropped; see module docstring

    # ---- tool.call / agent.message (delegation) ----

    def _on_tool_started(self, event: ToolUsageStartedEvent) -> None:
        if event.tool_name in _DELEGATION_TOOL_NAMES:
            return  # delegation is recorded as agent.message on the *finished* event
        # side_effect_class: conservative default — CrewAI tools don't declare one.
        inputs = {
            "tool_name": event.tool_name,
            "args": to_json_safe(_parse_tool_args(event.tool_args)),
            "side_effect_class": "external",
        }
        task_id = event.task_id or _UNKNOWN_TASK
        self._pending_tool_calls[task_id].append(
            _PendingToolCall(
                inputs=inputs, agent_role=event.agent_role, started_at=time.monotonic()
            )
        )

    def _on_tool_finished(self, event: ToolUsageFinishedEvent) -> None:
        if event.tool_name in _DELEGATION_TOOL_NAMES:
            self._emit_agent_message(event)
            return
        task_id = event.task_id or _UNKNOWN_TASK
        queue = self._pending_tool_calls.get(task_id)
        if not queue:
            return
        pending = queue.popleft()
        self.tool_call_count += 1
        result = {
            "result": to_json_safe(event.output),
            "status": "ok",
            "latency_ms": (time.monotonic() - pending.started_at) * 1000,
        }
        step = self._steps.get(task_id)
        step_id = step.step_id if step is not None else None
        with optional_step_scope(step_id), optional_agent_scope(pending.agent_role):
            self._boundary("tool.call", pending.inputs, result)

    def _on_tool_error(self, event: ToolUsageErrorEvent) -> None:
        if event.tool_name in _DELEGATION_TOOL_NAMES:
            return
        queue = self._pending_tool_calls.get(event.task_id or _UNKNOWN_TASK)
        if queue:
            queue.popleft()  # dropped; see module docstring

    def _emit_agent_message(self, event: ToolUsageFinishedEvent) -> None:
        args = _parse_tool_args(event.tool_args)
        message_type = _DELEGATION_TOOL_NAMES.get(event.tool_name, "other")
        content: dict[str, Any] = {
            key: value for key, value in args.items() if key != "coworker"
        }
        content["result"] = event.output
        task_id = event.task_id or _UNKNOWN_TASK
        step = self._steps.get(task_id)
        step_id = step.step_id if step is not None else None
        payload = {
            "from_agent": event.agent_role or "unknown",
            "to_agent": args.get("coworker", "unknown"),
            "content": to_json_safe(content),
            "message_type": message_type,
        }
        with optional_step_scope(step_id), optional_agent_scope(event.agent_role):
            self._emit("agent.message", payload)

    # ---- memory.read / memory.write ----

    def _on_memory_query_started(self, event: MemoryQueryStartedEvent) -> None:
        self._pending_memory_queries.append(
            _PendingMemoryOp(
                task_id=event.task_id or _UNKNOWN_TASK,
                agent_role=event.agent_role,
                query=event.query,
                limit=event.limit,
            )
        )

    def _on_memory_query_completed(self, event: MemoryQueryCompletedEvent) -> None:
        if not self._pending_memory_queries:
            return
        pending = self._pending_memory_queries.popleft()
        step = self._steps.get(pending.task_id)
        step_id = step.step_id if step is not None else None
        payload = {
            "store": "vector",  # CrewAI's default memory backend; see README
            "query": pending.query,
            "results": to_json_safe(event.results),
            "k": pending.limit,
            "latency_ms": event.query_time_ms,
        }
        with optional_step_scope(step_id), optional_agent_scope(pending.agent_role):
            self._emit("memory.read", payload)

    def _on_memory_query_failed(self, _event: MemoryQueryFailedEvent) -> None:
        if self._pending_memory_queries:
            self._pending_memory_queries.popleft()  # dropped; see module docstring

    def _on_memory_save_started(self, event: MemorySaveStartedEvent) -> None:
        self._pending_memory_saves.append(
            _PendingMemoryOp(
                task_id=event.task_id or _UNKNOWN_TASK, agent_role=event.agent_role
            )
        )

    def _on_memory_save_completed(self, event: MemorySaveCompletedEvent) -> None:
        if not self._pending_memory_saves:
            return
        pending = self._pending_memory_saves.popleft()
        step = self._steps.get(pending.task_id)
        step_id = step.step_id if step is not None else None
        payload = {
            "store": "vector",
            "key_or_ns": pending.agent_role or "default",
            "value": to_json_safe(event.value),
            "latency_ms": event.save_time_ms,
        }
        with optional_step_scope(step_id), optional_agent_scope(pending.agent_role):
            self._emit("memory.write", payload)

    def _on_memory_save_failed(self, _event: MemorySaveFailedEvent) -> None:
        if self._pending_memory_saves:
            self._pending_memory_saves.popleft()  # dropped; see module docstring
