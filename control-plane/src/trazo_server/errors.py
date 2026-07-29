"""Typed exceptions for the control plane (CODING_STANDARDS.md §1)."""

from __future__ import annotations


class TrazoServerError(Exception):
    """Root of every control-plane-raised exception."""


class BlobNotFoundError(TrazoServerError):
    """Raised by a BlobStore.get() when no blob exists for the given sha256."""

    def __init__(self, sha256: str) -> None:
        super().__init__(f"no blob stored for {sha256}")
        self.sha256 = sha256


class OpaUnavailableError(TrazoServerError):
    """Raised by an OpaClient.evaluate() on timeout, connection failure, or
    a non-2xx response from the OPA sidecar (TRZ-P6-03). The endpoint
    turns this into a 503 for the SDK, whose own TRAZO_POLICY_FAIL
    (ADR-006) decides fail-open/closed from there -- the control plane
    itself has no opinion on that call."""
