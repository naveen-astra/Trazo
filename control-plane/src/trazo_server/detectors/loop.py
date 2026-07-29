"""LoopDetector (TRZ-P5-04, AI_DEBUGGER.md §1-2).

Signature: the same tool/LLM/memory call — identical fingerprint —
repeated at least ``min_repeats`` times within the most recent
``window_events`` boundary calls. Config: ``TRAZO_DETECT_LOOP_MIN_REPEATS``
(default 4), ``TRAZO_DETECT_LOOP_WINDOW_EVENTS`` (default 20) —
AI_DEBUGGER.md §2's starting point was 5, tuned down to 4 against the
injected-failure corpus (TRZ-P5-05): content-pipeline's loop injector
(``demos/content-pipeline/chaos_run.py``) forces cross-task repetition
across ``_LOOP_AFFECTED_TAGS``, which names exactly 4 tasks — that demo
can never produce a 5th repeat without binding a tool to a task that
doesn't have it, so 5 was an unreachable threshold for half the corpus.

Deliberately does *not* also require "no state-hash progress" (the full
AI_DEBUGGER.md §1 wording): a demo agent can keep growing its own state
(e.g. an accumulating findings list) on every iteration while still
genuinely stuck re-issuing the identical call — repeated-fingerprint
count alone is the reliable, corpus-verified signal; state-hash
stagnation is ThrashDetector's more specific job.

Only ``llm.call``/``tool.call`` count as loop-eligible kinds — narrower
than ``RunWindow``'s full boundary-kind set. ``memory.read`` was in the
original set and had to come out: research-assistant checks the same
memory key every iteration by design (that's what makes it a working
scratchpad, not a bug), producing an identical fingerprint every single
run regardless of any injected fault — confirmed against the corpus
(TRZ-P5-05), where it produced a "loop" false positive on every
budget/thrash/drift run alongside the genuinely stuck ones. A repeated
read of the same key is normal; a repeated *call* that keeps producing
the same result is the actual stuck signature.
"""

from __future__ import annotations

import os

from trazo_server.detectors.base import Detection, RunWindow
from trazo_server.events import Event

_LOOP_ELIGIBLE_KINDS = frozenset({"llm.call", "tool.call"})


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
        self.min_repeats = min_repeats or _env_int("TRAZO_DETECT_LOOP_MIN_REPEATS", 4)
        self.window_events = window_events or _env_int(
            "TRAZO_DETECT_LOOP_WINDOW_EVENTS", 20
        )

    def on_event(self, event: Event, window: RunWindow) -> Detection | None:
        if event.kind not in _LOOP_ELIGIBLE_KINDS or event.fingerprint is None:
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
