"""BudgetDetector (TRZ-P5-04, AI_DEBUGGER.md §1-2).

Two independent signatures, either one sufficient:

- **Absolute**: cumulative ``cost_usd`` or token totals for the run
  exceed a configured budget.
- **Velocity**: one call's cost exceeds ``velocity_multiplier`` times the
  trailing mean of the prior calls' costs (Δcost/Δsteps spiking) — catches
  a runaway before the absolute ceiling is even reached.

Config: ``TRAZO_DETECT_BUDGET_MAX_COST_USD`` (default 1.0),
``TRAZO_DETECT_BUDGET_MAX_TOKENS`` (default 100000),
``TRAZO_DETECT_BUDGET_VELOCITY_MULTIPLIER`` (default 3.0) — starting
points (AI_DEBUGGER.md §2), tuned against the injected-failure corpus in
TRZ-P5-05. Velocity needs at least ``min_samples_for_velocity`` prior
calls (default 2) before it judges anything, so it never fires on a
run's first call for lack of a trailing mean to compare against.
"""

from __future__ import annotations

import os

from trazo_server.detectors.base import Detection, RunWindow
from trazo_server.events import Event


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


class BudgetDetector:
    id = "budget"

    def __init__(
        self,
        *,
        max_cost_usd: float | None = None,
        max_tokens: int | None = None,
        velocity_multiplier: float | None = None,
        min_samples_for_velocity: int = 2,
    ) -> None:
        self.max_cost_usd = max_cost_usd or _env_float(
            "TRAZO_DETECT_BUDGET_MAX_COST_USD", 1.0
        )
        self.max_tokens = max_tokens or _env_int(
            "TRAZO_DETECT_BUDGET_MAX_TOKENS", 100_000
        )
        self.velocity_multiplier = velocity_multiplier or _env_float(
            "TRAZO_DETECT_BUDGET_VELOCITY_MULTIPLIER", 3.0
        )
        self.min_samples_for_velocity = min_samples_for_velocity

    def on_event(self, event: Event, window: RunWindow) -> Detection | None:
        if event.kind != "llm.call":
            return None

        if (
            window.cost_usd_total > self.max_cost_usd
            or window.tokens_total > self.max_tokens
        ):
            return Detection(
                detector="budget",
                severity="critical",
                evidence_event_ids=[event.event_id],
                details={
                    "reason": "absolute_budget_exceeded",
                    "cost_usd_total": window.cost_usd_total,
                    "tokens_total": window.tokens_total,
                    "max_cost_usd": self.max_cost_usd,
                    "max_tokens": self.max_tokens,
                },
                window=window.as_summary(),
            )

        costs = list(window.recent_llm_costs)
        if len(costs) >= self.min_samples_for_velocity + 1:
            trailing = costs[:-1]
            current = costs[-1]
            trailing_mean = sum(trailing) / len(trailing)
            if trailing_mean > 0 and current > trailing_mean * self.velocity_multiplier:
                return Detection(
                    detector="budget",
                    severity="warn",
                    evidence_event_ids=[event.event_id],
                    details={
                        "reason": "cost_velocity_spike",
                        "current_cost_usd": current,
                        "trailing_mean_cost_usd": trailing_mean,
                        "velocity_multiplier": self.velocity_multiplier,
                    },
                    window=window.as_summary(),
                )

        return None
