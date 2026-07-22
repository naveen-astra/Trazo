"""Shared pytest fixtures for SDK tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from trazo.core.context import _reset_config_for_tests
from trazo.core.runtime import _reset_runtime_for_tests


@pytest.fixture(autouse=True)
def _reset_sdk_globals() -> Iterator[None]:
    """trazo.init() sets module-global config and starts a background
    Recorder — reset both around every test so tests can't leak
    initialization state (or a live shipper thread) into each other."""
    _reset_config_for_tests()
    _reset_runtime_for_tests()
    yield
    _reset_runtime_for_tests()
    _reset_config_for_tests()
