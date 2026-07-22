"""Smoke test for the overhead micro-benchmark harness (TRZ-P2-03 DoD:
"harness exists"). Doesn't assert the 10% budget itself — that's TRZ-P2-09,
against a real toy agent; timing-based hard assertions on a trivial
function in CI would just be flaky.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark.overhead import measure_boundary_overhead


def test_measure_boundary_overhead__returns_sane_timings() -> None:
    result = measure_boundary_overhead(iterations=50)

    assert result.baseline_seconds >= 0
    assert result.instrumented_seconds >= 0
    assert math.isfinite(result.overhead_ratio)
