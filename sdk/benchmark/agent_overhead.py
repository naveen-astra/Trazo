"""Real-agent overhead benchmark (TRZ-P2-09): the toy LangGraph agent
(``tests/agents/research_assistant.py``) run instrumented (via
``instrument()``, TRZ-P2-04) vs bare, with simulated per-call latency so
the SDK's fixed per-call overhead is measured as a fraction of a call cost
that looks like production — not the nanosecond-scale trivial function in
``benchmark/overhead.py`` (that harness's own docstring makes the same
point: a truly trivial baseline exaggerates the ratio).

Asserts the ARCHITECTURE.md §2 budget: SDK overhead <= 10% wall-clock.
Wired into the nightly workflow (.github/workflows/nightly.yml) — ``main``
exits non-zero when the budget is blown, which is what turns that job red.

``DEFAULT_LATENCY_SECONDS`` (200ms) approximates a fast LLM API call —
MASTER_PLAN.md's budget is phrased "on demo agents", i.e. against realistic
call latency, not a worst-case synthetic one. Measurement against this
harness showed the SDK's fixed per-call cost is a small, roughly constant
number of milliseconds (context/fingerprint/ULID bookkeeping); at 50ms
simulated latency that fixed cost is a large enough fraction of the call to
make the ratio noisy and machine-dependent, occasionally exceeding budget
on nothing more than scheduler jitter. 200ms gives a stable, still-strict
measurement, and a warm-up iteration (excluded from timing) absorbs
first-call import/JIT cost so it doesn't pollute either arm.

Run directly: ``uv run python -m benchmark.agent_overhead`` (from ``sdk/``).
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from agents.research_assistant import build_toy_graph, initial_state

from trazo.core.context import init as context_init
from trazo.core.recorder import Recorder
from trazo.integrations.langgraph import instrument

DEFAULT_ITERATIONS = 15
DEFAULT_LATENCY_SECONDS = 0.2
BUDGET_RATIO = 0.10


class _DiscardingShipper:
    """No-op Shipper stand-in: isolates Recorder/adapter overhead from
    network I/O, same rationale as ``benchmark/overhead.py``."""

    def enqueue(self, event: dict[str, Any]) -> None:
        pass

    def flush_and_stop(self, *, timeout: float = 5.0) -> None:
        pass


@dataclass(frozen=True)
class AgentOverheadResult:
    baseline_seconds: float
    instrumented_seconds: float
    iterations: int
    latency_seconds: float

    @property
    def overhead_ratio(self) -> float:
        """Fractional overhead: 0.10 == instrumented run took 10% longer."""
        if self.baseline_seconds == 0:
            return 0.0
        return (
            self.instrumented_seconds - self.baseline_seconds
        ) / self.baseline_seconds


def _run_bare(iterations: int, latency_seconds: float) -> float:
    warmup_graph, _counters = build_toy_graph(latency_seconds=latency_seconds)
    warmup_graph.invoke(initial_state())  # excluded: absorbs import/JIT cost

    start = time.perf_counter()
    for _ in range(iterations):
        graph, _counters = build_toy_graph(latency_seconds=latency_seconds)
        graph.invoke(initial_state())
    return time.perf_counter() - start


def _run_instrumented(iterations: int, latency_seconds: float) -> float:
    context_init(project="benchmark-agent")

    warmup_graph, _counters = build_toy_graph(latency_seconds=latency_seconds)
    warmup_recorder = Recorder(shipper=_DiscardingShipper())
    instrument(warmup_graph, recorder=warmup_recorder).invoke(initial_state())

    start = time.perf_counter()
    for _ in range(iterations):
        graph, _counters = build_toy_graph(latency_seconds=latency_seconds)
        recorder = Recorder(shipper=_DiscardingShipper())
        traced = instrument(graph, recorder=recorder)
        traced.invoke(initial_state())
    return time.perf_counter() - start


def measure_agent_overhead(
    *,
    iterations: int = DEFAULT_ITERATIONS,
    latency_seconds: float = DEFAULT_LATENCY_SECONDS,
) -> AgentOverheadResult:
    baseline = _run_bare(iterations, latency_seconds)
    instrumented = _run_instrumented(iterations, latency_seconds)
    return AgentOverheadResult(
        baseline_seconds=baseline,
        instrumented_seconds=instrumented,
        iterations=iterations,
        latency_seconds=latency_seconds,
    )


def main() -> int:
    result = measure_agent_overhead()
    print(
        f"toy agent: {result.iterations} iterations, "
        f"{result.latency_seconds * 1000:.0f}ms simulated call latency"
    )
    print(f"baseline:     {result.baseline_seconds:.3f}s")
    print(f"instrumented: {result.instrumented_seconds:.3f}s")
    print(
        f"overhead:     {result.overhead_ratio:.1%} "
        f"(budget: {BUDGET_RATIO:.0%}, ARCHITECTURE.md §2)"
    )
    if result.overhead_ratio > BUDGET_RATIO:
        print("FAIL: overhead budget exceeded", file=sys.stderr)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
