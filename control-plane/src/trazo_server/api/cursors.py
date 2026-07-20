"""Opaque pagination cursors (API_SPEC.md: "cursor opaque").

Keyset (seek) pagination, not OFFSET: the cursor anchors on the last row
a client saw, so a concurrent insert elsewhere in the table can never
shift an already-issued cursor's meaning — the next page is always
"everything past this exact row," never "skip N rows from the top."
"""

from __future__ import annotations

import base64
import json
from typing import Any


class InvalidCursorError(ValueError):
    """Raised when a client-supplied cursor doesn't decode to a valid payload."""


def encode_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str) -> dict[str, Any]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        decoded = json.loads(raw)
    except Exception as exc:
        raise InvalidCursorError(f"invalid cursor: {cursor!r}") from exc
    if not isinstance(decoded, dict):
        raise InvalidCursorError(f"invalid cursor: {cursor!r}")
    return decoded
