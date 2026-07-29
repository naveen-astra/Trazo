"""LoopDetector (TRZ-P5-04, AI_DEBUGGER.md §1-2).

Signature: the same tool/LLM/memory call — identical fingerprint —
repeated at least ``min_repeats`` times within the most recent
``window_events`` boundary calls. Config: ``TRAZO_DETECT_LOOP_MIN_REPEATS``
(default 5), ``TRAZO_DETECT_LOOP_WINDOW_EVENTS`` (default 20) — the
starting-point defaults AI_DEBUGGER.md §2 names, tuned against the
injected-failure corpus in TRZ-P5-05.

Deliberately does *not* also require "no state-hash progress" (the full
AI_DEBUGGER.md §1 wording): a demo agent can keep growing its own state
(e.g. an accumulating findings list) on every iteration while still
genuinely stuck re-issuing the identical call — repeated-fingerprint
count alone is the reliable, corpus-verified signal; state-hash
stagnation is ThrashDetector's more specific job.
"""

from __future__ import annotations

import os

from trazo_server.detectors.base import Detection, RunWindow
from trazo_server.events import Event

_BOUNDARY_KINDS = frozenset(
    {"llm.call", "tool.call", "memory.read", "memory.write", "human.checkpoint"}
)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


class LoopDetector:
    id = "loop"

    def __init__(
        self,
        *,
        min_repeats: int | None = None,
        window_events: int | None = None,
    ) -> None:
        self.min_repeats = min_repeats or _env_int("TRAZO_DETECT_LOOP_MIN_REPEATS", 5)
        self.window_events = window_events or _env_int(
            "TRAZO_DETECT_LOOP_WINDOW_EVENTS", 20
        )

    def on_event(self, event: Event, window: RunWindow) -> Detection | None:
        if event.kind not in _BOUNDARY_KINDS or event.fingerprint is None:
            return None

        recent = list(window.recent_boundaries)[-self.window_events :]
        matches = [
            b
            for b in recent
            if b.kind == event.kind and b.fingerprint == event.fingerprint
        ]
        if len(matches) < self.min_repeats:
            return None

        return Detection(
            detector="loop",
            severity="warn",
            evidence_event_ids=[b.event_id for b in matches],
            details={
                "kind": event.kind,
                "fingerprint": event.fingerprint,
                "repeat_count": len(matches),
                "min_repeats": self.min_repeats,
            },
            window=window.as_summary(),
        )
