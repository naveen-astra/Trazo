"""Typed exceptions for the control plane (CODING_STANDARDS.md §1)."""

from __future__ import annotations


class TrazoServerError(Exception):
    """Root of every control-plane-raised exception."""


class BlobNotFoundError(TrazoServerError):
    """Raised by a BlobStore.get() when no blob exists for the given sha256."""

    def __init__(self, sha256: str) -> None:
        super().__init__(f"no blob stored for {sha256}")
        self.sha256 = sha256
