"""LangChain callback handler bridging LangGraph node/LLM/tool activity
into Recorder (TRZ-P2-04) — SDK.md §3's LangGraph contract: step
boundaries via node-level middleware, LLM/tool capture via a LangChain
callbacks handler scoped to the run context.

Design notes (see exploration behind this file — verified empirically
against langgraph 0.2.76 / langchain-core 0.3.86, not assumed):

- LangGraph tags every node's own wrapper chain with
  ``metadata["langgraph_node"]``; that wrapper's ``on_chain_start``
  ``inputs``/``on_chain_end`` ``outputs`` are exactly the full graph state
  before/after that node — no need for ``stream_mode`` polling, and it's
  naturally ordered correctly (the wrapper starts before, and ends after,
  every LLM/tool call the node makes).
- LangGraph wraps each node in more than one nested chain carrying the
  *same* ``langgraph_node`` metadata; only the outermost one (the one
  whose parent isn't already a tracked step) is treated as the step
  boundary, so a node isn't double-recorded.
- LLM/tool calls are attributed to the *enclosing* step by walking
  ``parent_run_id`` up through every run this handler has seen — not by
  relying on contextvars persisting across separate callback invocations
  (they don't reliably: separate callbacks are separate calls, not nested
  frames of one call stack).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from trazo.core.context import (
    agent_scope,
    optional_agent_scope,
    optional_step_scope,
    step_scope,
)
from trazo.core.policy import PolicyHook
from trazo.core.pricing import estimate_cost_usd
from trazo.core.recorder import Recorder
from trazo.core.serialization import hash_state, to_json_safe
from trazo.core.ulid import new_step_id


@dataclass
class _StepState:
    step_id: str
    node_name: str
    index: int
    started_at: float


@dataclass
class _InFlightLlmCall:
    inputs: dict[str, Any]
    step: _StepState | None
    started_at: float


@dataclass
class _InFlightToolCall:
    inputs: dict[str, Any]
    step: _StepState | None
    started_at: float


class TrazoCallbackHandler(BaseCallbackHandler):
    """One instance per graph invocation; pass via ``config={"callbacks": [...]}``."""

    def __init__(
        self, recorder: Recorder, *, policy_hook: PolicyHook | None = None
    ) -> None:
        self._recorder = recorder
        self._policy_hook = policy_hook
        self._parents: dict[UUID, UUID | None] = {}
        self._active_steps: dict[UUID, _StepState] = {}
        self._llm_calls: dict[UUID, _InFlightLlmCall] = {}
        self._tool_calls: dict[UUID, _InFlightToolCall] = {}
        self._step_index = 0
        self._armed_for_raise = False

        self.step_count = 0

    @property
    def raise_error(self) -> bool:  # type: ignore[override]
        """LangChain's callback manager (``handle_event``) swallows every
        callback exception as a logged warning *unless*
        ``handler.raise_error`` is true, in which case it re-raises —
        the only mechanism by which a callback can actually abort an
        action (verified empirically, TRZ-P6-04: a plain raise from
        ``on_tool_start`` was silently logged and the tool ran anyway).

        Overridden as a *read-only* property (base class default: a
        plain writable ``False`` attribute, hence the ``type: ignore`` —
        LangChain only ever reads this attribute, never assigns to it,
        so narrowing it to read-only here is safe in practice) so it's
        true *only* for the exact instant ``on_tool_start`` is raising a
        ``PolicyDenied`` — never for the other eight callback methods,
        which must keep failing silently per AGENTS.md's hard rule (the
        SDK must never crash the host agent except for
        ``PolicyDenied``/``ReplayDivergence``)."""
        return self._armed_for_raise

    # ---- step boundaries: on_chain_start/on_chain_end filtered to nodes ----

    def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._parents[run_id] = parent_run_id
        node_name = (metadata or {}).get("langgraph_node")
        if not node_name or node_name == "__start__":
            return
        if parent_run_id is not None and self._find_enclosing_step(parent_run_id):
            return  # nested wrapper chain for a node already being tracked

        step_id = new_step_id()
        before_hash, before_snapshot, before_unhashed = hash_state(inputs)
        step = _StepState(
            step_id=step_id,
            node_name=node_name,
            index=self._step_index,
            started_at=time.monotonic(),
        )
        self._active_steps[run_id] = step
        self._step_index += 1
        self.step_count += 1

        payload: dict[str, Any] = {
            "name": node_name,
            "step_index": step.index,
            "state_before_hash": before_hash,
            "state_before": before_snapshot,
        }
        if before_unhashed:
            payload["unhashed_keys"] = before_unhashed
        with step_scope(step_id), agent_scope(node_name):
            self._recorder.emit("step.started", payload)

    def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        step = self._active_steps.pop(run_id, None)
        if step is None:
            return
        self._finish_step(step, outputs, status="ok")

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        step = self._active_steps.pop(run_id, None)
        if step is None:
            return
        # No output to hash on error — state didn't successfully transition,
        # so "after" is documented here as identical to "before" rather than
        # inventing a value; the error is visible via the run's own status.
        self._finish_step(step, None, status="error")

    def _finish_step(
        self, step: _StepState, outputs: dict[str, Any] | None, *, status: str
    ) -> None:
        self.step_count += 1
        duration_ms = (time.monotonic() - step.started_at) * 1000
        after_hash, after_snapshot, after_unhashed = hash_state(outputs or {})
        payload: dict[str, Any] = {
            "status": status,
            "state_after_hash": after_hash,
            "state_after": after_snapshot,
            "duration_ms": duration_ms,
        }
        if after_unhashed:
            payload["unhashed_keys"] = after_unhashed
        with step_scope(step.step_id), agent_scope(step.node_name):
            self._recorder.emit("step.finished", payload)

    # ---- llm.call ----

    def on_chat_model_start(
        self,
        serialized: dict[str, Any] | None,
        messages: list[list[Any]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._parents[run_id] = parent_run_id
        provider, model = _provider_and_model(serialized, kwargs)
        flat_messages = [
            to_json_safe(message) for batch in messages for message in batch
        ]
        inputs = {
            "provider": provider,
            "model": model,
            "params": _extract_params(kwargs),
            "messages_in": flat_messages,
        }
        self._llm_calls[run_id] = _InFlightLlmCall(
            inputs=inputs,
            step=self._find_enclosing_step(parent_run_id),
            started_at=time.monotonic(),
        )

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        in_flight = self._llm_calls.pop(run_id, None)
        if in_flight is None:
            return
        latency_ms = (time.monotonic() - in_flight.started_at) * 1000
        message_text = ""
        response_message: Any = None
        if response.generations and response.generations[0]:
            generation = response.generations[0][0]
            message_text = getattr(generation, "text", "") or ""
            response_message = getattr(generation, "message", None)

        usage = (response.llm_output or {}).get("token_usage", {}) or {}
        tokens_in = int(usage.get("prompt_tokens", 0) or 0)
        tokens_out = int(usage.get("completion_tokens", 0) or 0)

        result = {
            "response": to_json_safe(response_message)
            if response_message is not None
            else {"role": "assistant", "content": message_text},
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": estimate_cost_usd(
                provider=in_flight.inputs.get("provider"),
                model=in_flight.inputs.get("model"),
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            ),
            "latency_ms": latency_ms,
        }
        self._emit_boundary("llm.call", in_flight.inputs, result, step=in_flight.step)

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        # Recorder.boundary has no schema-valid way to represent a failed
        # llm.call without a response; dropped rather than emitting an
        # invalid event (see recorder.py's boundary() docstring).
        self._llm_calls.pop(run_id, None)

    # ---- tool.call ----

    def on_tool_start(
        self,
        serialized: dict[str, Any] | None,
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._parents[run_id] = parent_run_id
        tool_name = (serialized or {}).get("name", "unknown_tool")
        args: Any = inputs if inputs is not None else {"input": input_str}
        side_effect_class = "external"  # conservative default; see README
        json_safe_args = to_json_safe(args)

        # TRZ-P6-04: raising PolicyDenied here, before the tool ever runs,
        # is what makes "the blocked call never executes" true --
        # on_tool_start fires before LangChain dispatches to the tool's
        # own _run/_arun. ``_armed_for_raise`` is deliberately reset only
        # on the *success* path below, never in a finally: a finally runs
        # during the raising call's own stack unwinding, i.e. before
        # LangChain's handle_event gets to check handler.raise_error at
        # all -- disarming there would reset the flag a moment too early
        # and the exception would go right back to being silently logged
        # (this was tried and empirically failed while building this;
        # see the raise_error property's docstring for the mechanism).
        if self._policy_hook is not None:
            self._armed_for_raise = True
            self._policy_hook.check(
                kind="tool.call",
                tool_name=tool_name,
                args=json_safe_args if isinstance(json_safe_args, dict) else {},
                side_effect_class=side_effect_class,
            )
            self._armed_for_raise = False

        self._tool_calls[run_id] = _InFlightToolCall(
            inputs={
                "tool_name": tool_name,
                "args": json_safe_args,
                "side_effect_class": side_effect_class,
            },
            step=self._find_enclosing_step(parent_run_id),
            started_at=time.monotonic(),
        )

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        in_flight = self._tool_calls.pop(run_id, None)
        if in_flight is None:
            return
        latency_ms = (time.monotonic() - in_flight.started_at) * 1000
        result = {
            "result": to_json_safe(output),
            "status": "ok",
            "latency_ms": latency_ms,
        }
        self._emit_boundary("tool.call", in_flight.inputs, result, step=in_flight.step)

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self._tool_calls.pop(run_id, None)  # see on_llm_error's note

    # ---- shared helpers ----

    def _find_enclosing_step(self, run_id: UUID | None) -> _StepState | None:
        seen: set[UUID] = set()
        current = run_id
        while current is not None and current not in seen:
            step = self._active_steps.get(current)
            if step is not None:
                return step
            seen.add(current)
            current = self._parents.get(current)
        return None

    def _emit_boundary(
        self,
        kind: str,
        inputs: dict[str, Any],
        result: dict[str, Any],
        *,
        step: _StepState | None,
    ) -> None:
        step_id = step.step_id if step is not None else None
        node_name = step.node_name if step is not None else None
        with optional_step_scope(step_id), optional_agent_scope(node_name):
            self._recorder.boundary(kind, inputs, lambda: result)


def _provider_and_model(
    serialized: dict[str, Any] | None, kwargs: dict[str, Any]
) -> tuple[str, str]:
    class_name = "unknown"
    if serialized and serialized.get("id"):
        class_name = serialized["id"][-1]
    invocation_params = kwargs.get("invocation_params") or {}
    model = (
        invocation_params.get("model")
        or invocation_params.get("model_name")
        or "unknown"
    )
    return class_name, model


def _extract_params(kwargs: dict[str, Any]) -> dict[str, Any]:
    invocation_params = dict(kwargs.get("invocation_params") or {})
    invocation_params.pop("model", None)
    invocation_params.pop("model_name", None)
    invocation_params.pop("_type", None)
    return invocation_params
