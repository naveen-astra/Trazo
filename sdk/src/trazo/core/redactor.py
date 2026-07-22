"""Key-pattern redaction before events leave the process (TRZ-P2-03).

Config: ``TRAZO_REDACT_KEYS`` (ARCHITECTURE.md §6) — extra comma-separated
key substrings to redact, on top of a sane default set. Case-insensitive
substring match on dict keys, applied recursively to every payload before
it reaches the buffer/shipper — redaction happens in-process, never on
the server (a key that shouldn't leave the host must never be sent at all).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

_DEFAULT_REDACT_KEYS = (
    "password",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    # Specific credential-shaped names, not the bare substring "token" —
    # that collided with legitimate fields like llm.call's tokens_in/
    # tokens_out (EVENTS.md §2.3), redacting real usage metrics.
    "auth_token",
    "access_token",
    "refresh_token",
    "bearer_token",
    "session_token",
)
_REDACTED_PLACEHOLDER = "***REDACTED***"


class Redactor:
    """Recursively redacts dict values whose key matches a sensitive pattern."""

    def __init__(self, extra_keys: Iterable[str] = ()) -> None:
        self._patterns = tuple(
            k.lower() for k in (*_DEFAULT_REDACT_KEYS, *extra_keys) if k
        )

    def redact(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: (_REDACTED_PLACEHOLDER if self._is_sensitive(k) else self.redact(v))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [self.redact(v) for v in value]
        return value

    def _is_sensitive(self, key: object) -> bool:
        key_lower = str(key).lower()
        return any(pattern in key_lower for pattern in self._patterns)
