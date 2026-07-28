"""Replay report + divergence model (TRZ-P4-03, REPLAY_ENGINE.md §3, §5).

A replay session never writes back into the original run's event
stream — "replays are read-only over history" (REPLAY_ENGINE.md §2 point
3) — so every match, reorder, and divergence the Substituter finds is
recorded here instead, purely in-memory, and is what ``report.fidelity``
(§5) and ``trazo verify``'s CLI output (TRZ-P4-06) are built from.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReplayStepRecord:
    """One boundary call the Substituter successfully matched."""

    kind: str
    fingerprint: str
    matched_event_id: str
    matched_seq: int
    reordered: bool


@dataclass(frozen=True)
class DivergenceDetail:
    """Field-level context for a mismatch — "which part of the prompt
    changed" (REPLAY_ENGINE.md §3): the recorded normalized inputs next
    to the live ones, so a caller can diff them directly."""

    expected_seq: int | None
    expected_event_id: str | None
    expected_fingerprint: str | None
    live_fingerprint: str
    live_inputs: dict[str, Any]


class ReplayDivergence(Exception):
    """Raised in ``strict`` mode the moment a boundary call can't be
    answered by history: fingerprint mismatch beyond lookahead, cursor
    exhausted, or a kind never recorded at all (REPLAY_ENGINE.md §3)."""

    def __init__(self, kind: str, reason: str, detail: DivergenceDetail) -> None:
        self.kind = kind
        self.reason = reason
        self.detail = detail
        super().__init__(
            f"replay divergence on {kind!r} ({reason}): "
            f"expected event {detail.expected_event_id!r} "
            f"(fingerprint {detail.expected_fingerprint!r}), "
            f"live fingerprint {detail.live_fingerprint!r}"
        )


class ReplayReport:
    """Accumulates a replay session's steps and divergences; ``fidelity``
    is boundary fidelity (REPLAY_ENGINE.md §5) — matched / total."""

    def __init__(self) -> None:
        self.steps: list[ReplayStepRecord] = []
        self.divergences: list[ReplayDivergence] = []

    def record_match(
        self, *, kind: str, fingerprint: str, event_id: str, seq: int, reordered: bool
    ) -> None:
        self.steps.append(
            ReplayStepRecord(
                kind=kind,
                fingerprint=fingerprint,
                matched_event_id=event_id,
                matched_seq=seq,
                reordered=reordered,
            )
        )

    def record_divergence(self, divergence: ReplayDivergence) -> None:
        self.divergences.append(divergence)

    @property
    def fidelity(self) -> float:
        """Matched boundary calls / total boundary calls attempted. ``1.0``
        for a report with no boundary calls at all (nothing to diverge on)."""
        total = len(self.steps) + len(self.divergences)
        return 1.0 if total == 0 else len(self.steps) / total

    @property
    def reordered_count(self) -> int:
        return sum(1 for step in self.steps if step.reordered)
