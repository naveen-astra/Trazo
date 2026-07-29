"""ULID generation for server-minted IDs (TRZ-P5-06).

Every ID the SDK mints is a ULID (CODING_STANDARDS.md §3: ``run_``,
``evt_``, ``stp_`` prefixes) via ``trazo.core.ulid`` — but ``sdk`` and
``control-plane`` never cross-import (DEVELOPMENT_GUIDE.md), so a
``detection.raised`` event minted server-side (the only event kind the
control plane itself originates) needs its own copy of the same tiny,
dependency-free generator. Kept byte-for-byte identical to
``sdk/src/trazo/core/ulid.py`` on purpose — same format, same sort
order, same "no library dependency" reasoning.
"""

from __future__ import annotations

import os
import time

_CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # excludes I, L, O, U
_ULID_LENGTH = 26
_TIMESTAMP_BYTES = 6
_RANDOM_BYTES = 10


def new_ulid(*, timestamp_ms: int | None = None) -> str:
    """Generate a new ULID. ``timestamp_ms`` is injectable for tests only."""
    ts = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
    ts_bytes = ts.to_bytes(_TIMESTAMP_BYTES, byteorder="big")
    payload = ts_bytes + os.urandom(_RANDOM_BYTES)
    return _encode(payload)


def _encode(payload: bytes) -> str:
    value = int.from_bytes(payload, byteorder="big")
    chars = []
    for _ in range(_ULID_LENGTH):
        chars.append(_CROCKFORD_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def new_event_id() -> str:
    return f"evt_{new_ulid()}"


def new_detection_id() -> str:
    return f"det_{new_ulid()}"
