"""Unit tests for trazo.core.determinism.frozen_determinism (TRZ-P4-04)."""

from __future__ import annotations

import random
import time

import pytest

from trazo.core.determinism import frozen_determinism


def test_frozen_determinism__same_seed_reproduces_the_same_random_sequence() -> None:
    with frozen_determinism(seed=42):
        sequence1 = [random.random() for _ in range(5)]

    with frozen_determinism(seed=42):
        sequence2 = [random.random() for _ in range(5)]

    assert sequence1 == sequence2


def test_frozen_determinism__different_seeds_diverge() -> None:
    with frozen_determinism(seed=1):
        sequence1 = [random.random() for _ in range(5)]

    with frozen_determinism(seed=2):
        sequence2 = [random.random() for _ in range(5)]

    assert sequence1 != sequence2


def test_frozen_determinism__restores_random_state_on_exit() -> None:
    random.seed(999)
    before = random.getstate()

    with frozen_determinism(seed=0):
        random.random()

    assert random.getstate() == before


def test_frozen_determinism__restores_random_state_even_on_exception() -> None:
    random.seed(999)
    before = random.getstate()

    try:
        with frozen_determinism(seed=0):
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert random.getstate() == before


def test_frozen_determinism__freezes_time_time_and_monotonic() -> None:
    with frozen_determinism(seed=0, frozen_time=1000.0):
        t1 = time.time()
        t2 = time.monotonic()
        import time as time_module

        time_module.sleep(0.01)
        t3 = time.time()

    assert t1 == t2 == t3 == 1000.0


def test_frozen_determinism__restores_real_time_functions_on_exit() -> None:
    original_time_fn = time.time
    original_monotonic_fn = time.monotonic

    with frozen_determinism(seed=0, frozen_time=1000.0):
        pass

    assert time.time is original_time_fn
    assert time.monotonic is original_monotonic_fn
    # the real clock is moving again, not frozen at 1000.0
    assert time.time() != 1000.0


def test_frozen_determinism__seeds_numpy_random_when_installed() -> None:
    numpy = pytest.importorskip("numpy")

    with frozen_determinism(seed=7):
        sequence1 = numpy.random.rand(3).tolist()
    with frozen_determinism(seed=7):
        sequence2 = numpy.random.rand(3).tolist()

    assert sequence1 == sequence2


def test_frozen_determinism__restores_numpy_random_state_on_exit() -> None:
    numpy = pytest.importorskip("numpy")

    numpy.random.seed(123)
    before = numpy.random.get_state()

    with frozen_determinism(seed=0):
        numpy.random.rand()

    after = numpy.random.get_state()
    assert before[1].tolist() == after[1].tolist()
