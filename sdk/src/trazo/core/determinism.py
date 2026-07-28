"""Determinism aids for replay (TRZ-P4-04, REPLAY_ENGINE.md §6 point 1).

In-process nondeterminism *outside* a recorded boundary — user code
calling ``random()`` directly, or branching on wall-clock time — can
diverge a replay even when every boundary call matches perfectly. This
module is a best-effort mitigation, not a guarantee: it seeds ``random``
(and ``numpy.random``, if installed) and freezes ``time.time()``/
``time.monotonic()`` to a fixed value for the duration of a replay
session, so code that happens to only use those two sources of
nondeterminism reproduces exactly. Anything else (thread scheduling,
external randomness, a library with its own PRNG) is a residual gap —
made *visible* via divergence reporting rather than hidden, per
REPLAY_ENGINE.md §6's own framing.

``time.monotonic()`` frozen to a constant is still non-decreasing, so
nothing that depends on monotonic's one real guarantee breaks.

Scope warning: this patches ``time.time``/``time.monotonic`` at the
module level — process-wide for the duration of the context, not
scoped to one call stack or thread. Acceptable for a single-threaded
replay session (this SDK's only supported one today); would need a
different mechanism (e.g. patching each adapter's own time source) under
real concurrency.
"""

from __future__ import annotations

import random
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

_DEFAULT_SEED = 0


@contextmanager
def frozen_determinism(
    *, seed: int = _DEFAULT_SEED, frozen_time: float | None = None
) -> Iterator[None]:
    """Seed ``random``/``numpy.random`` and freeze ``time.time()``/
    ``time.monotonic()`` for the duration of this context, restoring the
    real functions and PRNG state on exit regardless of how the block
    exits (exception or not)."""
    random_state = random.getstate()
    random.seed(seed)

    numpy_random: Any = None
    numpy_state: Any = None
    try:
        import numpy as _numpy

        numpy_random = _numpy.random
        numpy_state = numpy_random.get_state()
        numpy_random.seed(seed)
    except ImportError:
        pass

    frozen = frozen_time if frozen_time is not None else time.time()
    original_time = time.time
    original_monotonic = time.monotonic
    time.time = lambda: frozen
    time.monotonic = lambda: frozen

    try:
        yield
    finally:
        time.time = original_time
        time.monotonic = original_monotonic
        random.setstate(random_state)
        if numpy_random is not None:
            numpy_random.set_state(numpy_state)
