"""Smoke test for the real-agent overhead benchmark (TRZ-P2-09).

Runs the actual harness end-to-end (few iterations, near-zero simulated
latency) to prove it executes and produces sane numbers, and exercises
``main()``'s pass/fail exit-code logic against fabricated results — a
timing-based hard assertion on the real 10% budget would be flaky in CI
(that's what the nightly workflow's dedicated job is for, run with a
realistic iteration count and latency).
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark.agent_overhead import AgentOverheadResult, main, measure_agent_overhead


def test_measure_agent_overhead__returns_sane_timings() -> None:
    result = measure_agent_overhead(iterations=2, latency_seconds=0.0)

    assert result.baseline_seconds >= 0
    assert result.instrumented_seconds >= 0
    assert result.iterations == 2
    assert math.isfinite(result.overhead_ratio)


def test_agent_overhead_result__overhead_ratio_is_a_fraction_of_baseline() -> None:
    result = AgentOverheadResult(
        baseline_seconds=2.0,
        instrumented_seconds=2.2,
        iterations=1,
        latency_seconds=0.05,
    )

    assert result.overhead_ratio == pytest.approx(0.1)


def test_agent_overhead_result__zero_baseline_reports_zero_overhead() -> None:
    result = AgentOverheadResult(
        baseline_seconds=0.0,
        instrumented_seconds=0.1,
        iterations=1,
        latency_seconds=0.0,
    )

    assert result.overhead_ratio == 0.0


def test_main__returns_0_when_within_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "benchmark.agent_overhead.measure_agent_overhead",
        lambda: AgentOverheadResult(
            baseline_seconds=1.0,
            instrumented_seconds=1.05,
            iterations=20,
            latency_seconds=0.05,
        ),
    )

    assert main() == 0


def test_main__returns_1_when_budget_blown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "benchmark.agent_overhead.measure_agent_overhead",
        lambda: AgentOverheadResult(
            baseline_seconds=1.0,
            instrumented_seconds=1.5,
            iterations=20,
            latency_seconds=0.05,
        ),
    )

    assert main() == 1
