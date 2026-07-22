"""ULID generation (TRZ-P2-01): Crockford Base32, 128 bits = 48-bit
millisecond timestamp + 80 bits of randomness, 26 characters.

Chosen over uuid4 because ULIDs sort lexically by creation time —
DATABASE.md relies on exactly this ("All IDs are ULIDs stored as text
(sortable, no coordination)"). CODING_STANDARDS.md §3 fixes the prefixes
(``run_``, ``evt_``, ``stp_``) this module's ``new_*_id`` helpers use.
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


def ulid_timestamp_ms(ulid: str) -> int:
    """Recover the embedded millisecond timestamp — for tests/debugging."""
    value = _decode(ulid)
    return value >> (8 * _RANDOM_BYTES)


def _encode(payload: bytes) -> str:
    value = int.from_bytes(payload, byteorder="big")
    chars = []
    for _ in range(_ULID_LENGTH):
        chars.append(_CROCKFORD_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def _decode(ulid: str) -> int:
    value = 0
    for char in ulid:
        value = (value << 5) | _CROCKFORD_ALPHABET.index(char.upper())
    return value


def new_run_id() -> str:
    return f"run_{new_ulid()}"


def new_event_id() -> str:
    return f"evt_{new_ulid()}"


def new_step_id() -> str:
    return f"stp_{new_ulid()}"
