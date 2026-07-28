"""Recorder: mode-switched RECORD/REPLAY boundary interception (TRZ-P2-03,
REPLAY mode wired in TRZ-P4-02).

Adapters call ``boundary(kind, inputs, execute_fn)`` — the single code
path that guarantees record/replay symmetry (CODING_STANDARDS.md §4:
"modes over subclasses for the recorder"; AGENTS.md: "every non-
deterministic boundary goes through Recorder.boundary... in both record
and replay mode. A bypassed boundary is a highest-severity bug").

In REPLAY mode, ``execute_fn`` is *never called* — the whole point is
that the outside world does not run again (REPLAY_ENGINE.md §1). The
Substituter answers the call from the loaded bundle instead, and the
match/divergence is recorded into the local ``ReplayReport`` — never
shipped as a new event; replays are read-only over history
(REPLAY_ENGINE.md §2 point 3).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TypeVar

from trazo.core.context import current_agent_id, current_run_context, current_step_id
from trazo.core.fingerprint import FINGERPRINTED_KINDS, fingerprint_for
from trazo.core.redactor import Redactor
from trazo.core.shipper import RECOMMENDED_SHUTDOWN_TIMEOUT_SECONDS, Shipper
from trazo.core.substituter import Substituter
from trazo.core.ulid import new_event_id
from trazo.errors import NoActiveRunError, ReplayNotConfiguredError

T = TypeVar("T", bound=dict[str, Any])


class RecorderMode(Enum):
    RECORD = "record"
    REPLAY = "replay"


class Recorder:
    """One instance per ``trazo.init()`` call; adapters call its methods."""

    def __init__(
        self,
        *,
        shipper: Shipper,
        redactor: Redactor | None = None,
        mode: RecorderMode = RecorderMode.RECORD,
        substituter: Substituter | None = None,
    ) -> None:
        self._shipper = shipper
        self._redactor = redactor or Redactor()
        self.mode = mode
        self.substituter = substituter

    def emit(self, kind: str, payload: dict[str, Any]) -> None:
        """Record a non-boundary event (run.started, step.started, ...) —
        no execute_fn, no fingerprint.

        A no-op in REPLAY mode: adapters call ``emit`` for run/step
        lifecycle events regardless of mode (they have no execute_fn to
        substitute), but replays never ship anything new — read-only over
        history (REPLAY_ENGINE.md §2 point 3), same as ``boundary``.
        """
        if self.mode is RecorderMode.REPLAY:
            return
        self._ship_event(kind, payload)

    def boundary(
        self,
        kind: str,
        inputs: dict[str, Any],
        execute_fn: Callable[[], T],
    ) -> T:
        """Execute ``execute_fn`` for real and record one event combining
        ``inputs`` with whatever result fields it returns.

        On failure, ``execute_fn``'s exception propagates untouched and no
        event is recorded for the failed attempt: synthesizing a schema-
        valid error payload needs kind-specific knowledge only the adapter
        has (e.g. tool.call's ``status``/``error`` fields don't exist on
        llm.call). An adapter that wants an error event should catch the
        exception itself and call ``emit``/``boundary`` again with a
        payload it knows is complete for that kind.

        In REPLAY mode, ``execute_fn`` is never called: the Substituter
        answers from the loaded bundle (or raises ``ReplayDivergence`` in
        strict mode) instead.
        """
        if self.mode is RecorderMode.REPLAY:
            if self.substituter is None:
                raise ReplayNotConfiguredError(
                    "Recorder is in REPLAY mode but has no Substituter — "
                    "construct it with substituter=Substituter(bundle, ...)"
                )
            return self.substituter.substitute(kind, inputs)  # type: ignore[return-value]
        result = execute_fn()
        payload: dict[str, Any] = {**inputs, **result}
        fingerprint = (
            fingerprint_for(kind, payload) if kind in FINGERPRINTED_KINDS else None
        )
        self._ship_event(kind, payload, fingerprint=fingerprint)
        return result

    def shutdown(
        self, *, timeout: float = RECOMMENDED_SHUTDOWN_TIMEOUT_SECONDS
    ) -> None:
        """Flush buffered events and stop the shipper thread. The atexit
        hook does this too; call explicitly for a deterministic flush in
        short-lived processes (CLI invocations, tests)."""
        self._shipper.flush_and_stop(timeout=timeout)

    def _ship_event(
        self, kind: str, payload: dict[str, Any], *, fingerprint: str | None = None
    ) -> None:
        ctx = current_run_context()
        if ctx is None:
            raise NoActiveRunError()

        envelope: dict[str, Any] = {
            "schema": "trazo.v1",
            "event_id": new_event_id(),
            "run_id": ctx.run_id,
            "project": ctx.project,
            "seq": ctx.next_seq(),
            "ts": _now_iso(),
            "kind": kind,
            "payload": self._redactor.redact(payload),
        }
        step_id = current_step_id()
        if step_id is not None:
            envelope["step_id"] = step_id
        agent_id = current_agent_id()
        if agent_id is not None:
            envelope["agent_id"] = agent_id
        if fingerprint is not None:
            envelope["fingerprint"] = fingerprint

        self._shipper.enqueue(envelope)


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
