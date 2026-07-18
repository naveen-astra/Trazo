"""Placeholder test proving the package imports and is versioned (TRZ-P0-03)."""

import trazo


def test_package__exposes_version() -> None:
    assert isinstance(trazo.__version__, str)
    assert trazo.__version__
