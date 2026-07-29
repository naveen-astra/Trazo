"""ThrashDetector (TRZ-P5-04, AI_DEBUGGER.md §1-2).

Signature: several distinct tools invoked recently, but the run's state
hasn't actually changed across the last ``step_window`` steps — busy,
but making no real progress. Requires *both* conditions: tool-call
diversity alone (an agent legitimately trying several tools) isn't
thrash without the accompanying state stagnation, and vice versa.

Config: ``TRAZO_DETECT_THRASH_MIN_DISTINCT_TOOLS`` (default 2),
``TRAZO_DETECT_THRASH_STEP_WINDOW`` (default 6). AI_DEBUGGER.md §2 names
4+ distinct tools as its starting point; defaulted lower here because
both demo agents this corpus is built from only expose 3 tools each in
total, so "4+" could never fire against real, corpus-verified thrash
runs — an explicit, documented tuning against the actual corpus (exactly
what TRZ-P5-05 exists to formalize further).
"""

from __future__ import annotations

import os

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
        min_distinct_tools: int | None = None,
        step_window: int | None = None,
    ) -> None:
        self.min_distinct_tools = min_distinct_tools or _env_int(
            "TRAZO_DETECT_THRASH_MIN_DISTINCT_TOOLS", 2
        )
        self.step_window = step_window or _env_int("TRAZO_DETECT_THRASH_STEP_WINDOW", 6)

    def on_event(self, event: Event, window: RunWindow) -> Detection | None:
        if event.kind != "tool.call":
            return None

        recent_hashes = list(window.recent_state_hashes)[-self.step_window :]
        if len(recent_hashes) < self.step_window:
            return None  # not enough steps yet to judge "no progress"
        if len(set(recent_hashes)) > 1:
            return None  # state did change — real progress, not thrash

        recent_tools = list(window.recent_tool_names)
        distinct_tools = set(recent_tools)
        if len(distinct_tools) < self.min_distinct_tools:
            return None

        recent_boundary_ids = [
            b.event_id for b in window.recent_boundaries if b.kind == "tool.call"
        ]
        return Detection(
            detector="thrash",
            severity="warn",
            evidence_event_ids=recent_boundary_ids,
            details={
                "distinct_tools": sorted(distinct_tools),
                "min_distinct_tools": self.min_distinct_tools,
                "step_window": self.step_window,
                "unchanged_state_hash": recent_hashes[0],
            },
            window=window.as_summary(),
        )
