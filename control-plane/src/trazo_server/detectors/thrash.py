"""ThrashDetector (TRZ-P5-04, AI_DEBUGGER.md §1-2).

Signature: several distinct tool calls made recently, none of which have
turned up anything the run hasn't already seen, and all of which came
back with the same result — busy, but cycling through a fixed, unhelpful
repertoire instead of making real progress.

The last clause is what separates thrash from a healthy retry pattern.
An agent that revisits earlier queries still learns something each time:
different queries return different results. An agent whose different
queries all return the same result (``no results``, the same error, an
empty list) is asking a tool that has stopped answering. Measuring only
whether the *calls* repeat could not tell the two apart, and fired on
every long run in the benchmark corpus -- budget and drift runs included
(precision 33%); requiring the results to collapse removes those.

AI_DEBUGGER.md §1's literal wording ties "no progress" to step.finished
state-hash stagnation — the same wording LoopDetector's docstring
already explains is unworkable (see ``loop.py``), and it's just as
unworkable here, for the same reason: a real agent's checkpointed state
almost always carries some monotonically-moving bookkeeping field (an
iteration counter, a query-in-flight slot), so the *full* state hash
never repeats even when the run is provably stuck. Confirmed directly
against the corpus (TRZ-P5-02, TRZ-P5-05): research-assistant's thrash
injector cycles the planner through the same 3 queries against a
corrupted tool, never once producing two identical state hashes, yet
never learning anything new either. "No progress" is measured instead
by fingerprint novelty on ``tool.call`` events (already sitting in the
window, no new tracking needed beyond ``RunWindow.recent_tool_fingerprints``):
once every fingerprint in the second half of the recent window has
already appeared in the first half, the run has stopped discovering
anything, regardless of what its bookkeeping state hash says. A window
where one fingerprint simply dominates (one exact call repeated, plus a
single stale one-off earlier) is excluded too — that's an exact-repeat
loop wearing a Thrash costume, not several calls genuinely cycling; it's
LoopDetector's signature, not this one's (verified against the corpus:
without this exclusion, every injected-loop run also tripped Thrash).

Config: ``TRAZO_DETECT_THRASH_MIN_DISTINCT_CALLS`` (default 2),
``TRAZO_DETECT_THRASH_WINDOW_CALLS`` (default 6). AI_DEBUGGER.md §2
names 4+ distinct *tools* as its starting point; this counts distinct
*fingerprints* instead (tool name + args), because both demo agents in
this corpus mostly re-invoke the same one or two tool names with
different arguments while stuck (a cycling search query, not a
different tool) — "4+ distinct tool names" could never fire against the
real corpus, and "distinct tool name" isn't actually what separates a
genuinely diverse, healthy retry pattern from a stuck one; the argument
diversity is.
"""

from __future__ import annotations

import os
from collections import Counter

from trazo_server.detectors.base import Detection, RunWindow
from trazo_server.events import Event


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


class ThrashDetector:
    id = "thrash"

    def __init__(
        self,
        *,
        min_distinct_calls: int | None = None,
        window_calls: int | None = None,
    ) -> None:
        self.min_distinct_calls = min_distinct_calls or _env_int(
            "TRAZO_DETECT_THRASH_MIN_DISTINCT_CALLS", 2
        )
        self.window_calls = window_calls or _env_int(
            "TRAZO_DETECT_THRASH_WINDOW_CALLS", 6
        )

    def on_event(self, event: Event, window: RunWindow) -> Detection | None:
        if event.kind != "tool.call":
            return None

        recent_fps = list(window.recent_tool_fingerprints)[-self.window_calls :]
        if len(recent_fps) < self.window_calls:
            return None  # not enough calls yet to judge "no progress"

        distinct_fps = {fp for fp in recent_fps if fp is not None}
        if len(distinct_fps) < self.min_distinct_calls:
            return None  # too little variety to call this "thrash" vs. a plain loop

        counts = Counter(fp for fp in recent_fps if fp is not None)
        if counts and max(counts.values()) > len(recent_fps) - self.min_distinct_calls:
            # one fingerprint dominates the window (one exact call repeated,
            # plus a single stale one-off earlier) -- that's an exact-repeat
            # loop, not several calls genuinely cycling with no progress.
            return None

        recent_results = list(window.recent_tool_result_keys)[-self.window_calls :]
        if len(set(recent_results)) > 1:
            # Different calls are still returning different things: the
            # run is revisiting calls but learning from them.
            return None

        half = len(recent_fps) // 2
        seen_first_half = set(recent_fps[:half])
        novel_in_second_half = [
            fp
            for fp in recent_fps[half:]
            if fp is not None and fp not in seen_first_half
        ]
        if novel_in_second_half:
            return None  # still turning up something new -- real progress

        recent_names = list(window.recent_tool_names)[-self.window_calls :]
        recent_boundary_ids = [
            b.event_id for b in window.recent_boundaries if b.kind == "tool.call"
        ][-self.window_calls :]
        return Detection(
            detector="thrash",
            severity="warn",
            evidence_event_ids=recent_boundary_ids,
            details={
                "distinct_tool_names": sorted(set(recent_names)),
                "distinct_fingerprint_count": len(distinct_fps),
                "distinct_result_count": len(set(recent_results)),
                "min_distinct_calls": self.min_distinct_calls,
                "window_calls": self.window_calls,
            },
            window=window.as_summary(),
        )
