"""The Substituter: replay-time boundary matching (TRZ-P4-02,
REPLAY_ENGINE.md §2).

Maintains one pending-index queue per event kind (seeded from the loaded
``ReplayBundle``, in seq order). For each live boundary call:

1. Compute the live fingerprint from the live inputs — the *same*
   ``trazo.core.fingerprint`` code recording used, so a byte-identical
   input always produces a byte-identical fingerprint (AGENTS.md's "one
   fingerprint implementation" rule is exactly what makes this matching
   possible at all).
2. **Exact match**: the front of the pending queue has the same
   fingerprint — the normal case. Consume it, advance.
3. **Lookahead match**: one of the next ``LOOKAHEAD`` pending entries
   matches — the recording came from a framework that parallelizes.
   Consume it out of order; the report marks it ``reordered``.
4. **Divergence**: neither — see ``replay_report.ReplayDivergence``.
"""

from __future__ import annotations

from typing import Any

from trazo.core.fingerprint import fingerprint_for
from trazo.core.replay_bundle import RecordedEvent, ReplayBundle
from trazo.core.replay_report import DivergenceDetail, ReplayDivergence, ReplayReport

LOOKAHEAD = 3

# EVENTS.md §2.3: the fields each fingerprinted kind's payload carries as
# *input* — everything else in a recorded event's payload is the result
# a live call would have produced, and is exactly what a substituted
# boundary call must hand back.
_INPUT_FIELDS_BY_KIND: dict[str, frozenset[str]] = {
    "llm.call": frozenset({"provider", "model", "params", "messages_in"}),
    "tool.call": frozenset({"tool_name", "args", "side_effect_class"}),
    "memory.read": frozenset({"store", "query", "k"}),
    "memory.write": frozenset({"store", "key_or_ns", "value"}),
    "human.checkpoint": frozenset({"prompt"}),
}


def result_from_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The result-shaped subset of a recorded event's payload — what
    ``execute_fn()`` would have returned, had it actually run."""
    input_fields = _INPUT_FIELDS_BY_KIND.get(kind, frozenset())
    return {k: v for k, v in payload.items() if k not in input_fields}


class Substituter:
    """One per replay session (REPLAY_ENGINE.md §4's ``replay.load()``).
    ``mode="strict"`` raises ``ReplayDivergence`` on the first mismatch;
    ``mode="lenient"`` records it and returns the recorded-at-cursor
    result anyway, continuing (REPLAY_ENGINE.md §3)."""

    def __init__(
        self,
        bundle: ReplayBundle,
        *,
        mode: str = "strict",
        report: ReplayReport | None = None,
    ) -> None:
        if mode not in ("strict", "lenient"):
            raise ValueError(f"mode must be 'strict' or 'lenient', got {mode!r}")
        self._bundle = bundle
        self._mode = mode
        self.report = report if report is not None else ReplayReport()
        self._pending: dict[str, list[int]] = {}
        self._step_cursor: dict[str, int] = {"step.started": 0, "step.finished": 0}

    def _pending_indices(self, kind: str) -> list[int]:
        if kind not in self._pending:
            self._pending[kind] = list(range(len(self._bundle.events_by_kind(kind))))
        return self._pending[kind]

    def check_step(self, kind: str, payload: dict[str, Any]) -> None:
        """Compare a live step.started/step.finished's state hash against
        the bundle's recorded value at the same ordinal position, feeding
        ``report.state_fidelity`` (REPLAY_ENGINE.md §5) — separate from
        boundary fidelity, and not fingerprint-matched at all (steps
        aren't in ``FINGERPRINTED_KINDS``). A no-op for any other kind."""
        if kind not in self._step_cursor:
            return
        hash_field = (
            "state_before_hash" if kind == "step.started" else "state_after_hash"
        )
        events = self._bundle.events_by_kind(kind)
        cursor = self._step_cursor[kind]
        recorded = events[cursor] if cursor < len(events) else None
        self._step_cursor[kind] = cursor + 1

        self.report.record_step_result(
            kind=kind,
            step_index=cursor,
            recorded_hash=recorded.payload.get(hash_field) if recorded else None,
            recomputed_hash=payload.get(hash_field),
        )

    def substitute(self, kind: str, inputs: dict[str, Any]) -> dict[str, Any]:
        live_fp = fingerprint_for(kind, inputs)
        events = self._bundle.events_by_kind(kind)
        pending = self._pending_indices(kind)

        match_position = self._find_match(events, pending, live_fp)
        if match_position is not None:
            event_idx = pending.pop(match_position)
            event = events[event_idx]
            self.report.record_match(
                kind=kind,
                fingerprint=live_fp,
                event_id=event.event_id,
                seq=event.seq,
                reordered=match_position != 0,
            )
            return result_from_payload(kind, event.payload)

        return self._diverge(kind, events, pending, live_fp, inputs)

    def _find_match(
        self, events: list[RecordedEvent], pending: list[int], live_fp: str
    ) -> int | None:
        for position in range(min(len(pending), LOOKAHEAD + 1)):
            if events[pending[position]].fingerprint == live_fp:
                return position
        return None

    def _diverge(
        self,
        kind: str,
        events: list[RecordedEvent],
        pending: list[int],
        live_fp: str,
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        expected = events[pending[0]] if pending else None
        detail = DivergenceDetail(
            expected_seq=expected.seq if expected else None,
            expected_event_id=expected.event_id if expected else None,
            expected_fingerprint=expected.fingerprint if expected else None,
            live_fingerprint=live_fp,
            live_inputs=inputs,
        )
        divergence = ReplayDivergence(
            kind, "exhausted" if expected is None else "mismatch", detail
        )
        self.report.record_divergence(divergence)

        if self._mode == "strict":
            raise divergence

        # lenient: fall back to the recorded-at-cursor result and keep
        # going, per REPLAY_ENGINE.md §3 — but only if there *is* one;
        # a kind with nothing left (or never recorded at all) has no
        # fallback, so even lenient mode must raise.
        if expected is None:
            raise divergence
        pending.pop(0)
        return result_from_payload(kind, expected.payload)
