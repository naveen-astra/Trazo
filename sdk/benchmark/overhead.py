"""Recorder overhead micro-benchmark harness (TRZ-P2-03).

Measures the SDK's own instrumentation overhead in isolation — wrapping a
trivial function in ``Recorder.boundary`` vs calling it directly, with a
no-op Shipper so network I/O (which happens on the Shipper's own
background thread and never blocks the caller anyway) isn't conflated
with the caller-thread overhead this budget is actually about.

This is the foundation TRZ-P2-09 applies to a real toy agent in nightly
CI, asserting ARCHITECTURE.md §2's budget: SDK overhead <= 10% wall-clock.
P2-03's job is just for this harness to exist and produce a number; P2-09
owns picking a real agent and wiring the threshold assertion.

Run directly: ``uv run python -m benchmark.overhead`` (from ``sdk/``).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from trazo.core.context import run_scope
from trazo.core.recorder import Recorder

DEFAULT_ITERATIONS = 5_000


class _DiscardingShipper:
    """No-op Shipper stand-in: isolates Recorder/context overhead from
    network I/O for this specific measurement."""

    def enqueue(self, event: dict[str, Any]) -> None:
        pass

    def flush_and_stop(self, *, timeout: float = 5.0) -> None:
        pass


@dataclass(frozen=True)
class OverheadResult:
    baseline_seconds: float
    instrumented_seconds: float

    @property
    def overhead_ratio(self) -> float:
        """Fractional overhead: 0.10 == instrumented run took 10% longer."""
        if self.baseline_seconds == 0:
            return 0.0
        return (
            self.instrumented_seconds - self.baseline_seconds
        ) / self.baseline_seconds


def _trivial_tool_call(x: int) -> int:
    return x * 2


def measure_boundary_overhead(
    *, iterations: int = DEFAULT_ITERATIONS
) -> OverheadResult:
    start = time.perf_counter()
    for i in range(iterations):
        _trivial_tool_call(i)
    baseline = time.perf_counter() - start

    recorder = Recorder(shipper=_DiscardingShipper())
    start = time.perf_counter()
    with run_scope("benchmark"):
        for i in range(iterations):
            recorder.boundary(
                "tool.call",
                {
                    "tool_name": "trivial",
                    "args": {"x": i},
                    "side_effect_class": "read",
                },
                lambda i=i: {
                    "result": _trivial_tool_call(i),
                    "status": "ok",
                    "latency_ms": 0,
                },
            )
    instrumented = time.perf_counter() - start

    return OverheadResult(baseline_seconds=baseline, instrumented_seconds=instrumented)


def main() -> None:
    result = measure_boundary_overhead()
    print(f"baseline:     {result.baseline_seconds:.4f}s")
    print(f"instrumented: {result.instrumented_seconds:.4f}s")
    print(f"overhead:     {result.overhead_ratio:.1%}")
    print(
        "\nNote: the baseline call here (`x * 2`) costs nanoseconds, so the "
        "SDK's fixed per-call overhead (context manager, fingerprint sha256, "
        "ULID generation) necessarily dominates and produces a huge-looking "
        "percentage. That is expected and is NOT the ARCHITECTURE.md §2 "
        "<=10% budget check — TRZ-P2-09 measures overhead against a real "
        "toy agent, where tool/LLM call latency is milliseconds-to-seconds "
        "and the same fixed overhead becomes a small fraction of it."
    )


if __name__ == "__main__":
    main()
