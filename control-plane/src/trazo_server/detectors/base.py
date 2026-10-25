"""Detector contract (TRZ-P5-03, AI_DEBUGGER.md §2).

Every detector must be a pure function of ``(event, window)`` — no I/O,
no store access; anything a detector needs must be derivable from the
event stream alone. That's what makes the exact same detector code
runnable both online (``DetectorWorker``, bus-driven) and offline
(``benchmark/detection/runner.py``, fed recorded streams directly, no
bus, no worker) — "same code online and offline is the point" (§3).
``tests/test_detectors_purity.py`` enforces the no-I/O half of that
contract by AST-scanning every module in this package for disallowed
imports.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass
from typing import Any, Protocol

from trazo_server.events import Event

# EVENTS.md §2.3: the boundary kinds a window's ring buffer tracks.
_BOUNDARY_KINDS = frozenset(
    {"llm.call", "tool.call", "memory.read", "memory.write", "human.checkpoint"}
)

_DEFAULT_WINDOW_SIZE = 50


def result_key(result: Any) -> str:
    """A stable digest of a tool call's result, so a window can tell
    whether calls are returning anything new without holding the results
    themselves."""
    encoded = json.dumps(result, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Detection:
    """What a detector reports — mirrors ``DetectionRaisedPayload``
    (``trazo_server.events``) field for field, so raising one is a
    straight ``payload=detection.__dict__``-shaped construction."""

    detector: str  # "loop" | "budget" | "thrash" | "drift"
    severity: str  # "info" | "warn" | "critical"
    evidence_event_ids: list[str]
    details: dict[str, Any]
    window: dict[str, Any]


@dataclass(frozen=True)
class BoundaryRecord:
    """One boundary event's identity, as a window remembers it — enough
    for a detector to compare recent calls without holding the full
    original event around."""

    event_id: str
    kind: str
    fingerprint: str | None
    seq: int


class RunWindow:
    """Per-run rolling state every detector reads from: ring buffers of
    recent boundary events and step state-hashes, running cost/token
    totals. Rebuilt fully from ``TraceStore`` on worker restart — never
    persisted itself (``DetectorWorker._rebuild_window``, TRZ-P5-03's
    "restart rebuild" DoD)."""

    def __init__(self, run_id: str, *, max_size: int = _DEFAULT_WINDOW_SIZE) -> None:
        self.run_id = run_id
        self.max_size = max_size
        self.recent_boundaries: deque[BoundaryRecord] = deque(maxlen=max_size)
        self.recent_state_hashes: deque[str] = deque(maxlen=max_size)
        self.recent_llm_costs: deque[float] = deque(maxlen=max_size)
        self.recent_tool_names: deque[str] = deque(maxlen=max_size)
        self.recent_tool_fingerprints: deque[str | None] = deque(maxlen=max_size)
        self.recent_tool_result_keys: deque[str] = deque(maxlen=max_size)
        self.cost_usd_total = 0.0
        self.tokens_total = 0
        self.step_count = 0
        # Every event_id already folded in. A redelivered event (bus reclaim
        # after a failed attempt) must not be counted twice: the totals
        # here are cumulative, so a double count would inflate cost and
        # step totals for the rest of the run. One string per event, and a
        # window only lives for its run.
        self._recorded_event_ids: set[str] = set()

    def record(self, event: Event) -> bool:
        """Fold one event into the rolling state. Called for *every*
        event, before dispatching to detectors — a detector always sees
        the window as of (and including) the event it's judging.

        Returns False, and changes nothing, for an event already recorded."""
        if event.event_id in self._recorded_event_ids:
            return False
        self._recorded_event_ids.add(event.event_id)
        if event.kind in _BOUNDARY_KINDS:
            self.recent_boundaries.append(
                BoundaryRecord(
                    event_id=event.event_id,
                    kind=event.kind,
                    fingerprint=event.fingerprint,
                    seq=event.seq,
                )
            )
        if event.kind == "llm.call":
            self.cost_usd_total += event.payload.cost_usd
            self.tokens_total += event.payload.tokens_in + event.payload.tokens_out
            self.recent_llm_costs.append(event.payload.cost_usd)
        if event.kind == "tool.call":
            self.recent_tool_names.append(event.payload.tool_name)
            self.recent_tool_fingerprints.append(event.fingerprint)
            self.recent_tool_result_keys.append(result_key(event.payload.result))
        if event.kind == "step.finished":
            self.recent_state_hashes.append(event.payload.state_after_hash)
            self.step_count += 1
        return True

    def as_summary(self) -> dict[str, Any]:
        """A JSON-safe snapshot for ``Detection.window`` — evidence
        context, not a full state dump."""
        return {
            "step_count": self.step_count,
            "cost_usd_total": self.cost_usd_total,
            "tokens_total": self.tokens_total,
            "recent_boundary_count": len(self.recent_boundaries),
        }


class Detector(Protocol):
    """``id`` names the detector (matches ``DetectorName`` in
    ``trazo_server.events``); ``on_event`` returns a ``Detection`` the
    moment its condition is met, or ``None`` otherwise. Deterministic:
    the same event sequence must always produce the same detections (the
    LLM drift classifier, TRZ-P5-07, is the one sanctioned exception —
    its nondeterminism is measured, not hidden)."""

    id: str

    def on_event(self, event: Event, window: RunWindow) -> Detection | None: ...
