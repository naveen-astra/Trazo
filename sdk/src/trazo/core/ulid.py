"""ULID generation (TRZ-P2-01): Crockford Base32, 128 bits = 48-bit
millisecond timestamp + 80 bits of randomness, 26 characters.

Chosen over uuid4 because ULIDs sort lexically by creation time —
DATABASE.md relies on exactly this ("All IDs are ULIDs stored as text
(sortable, no coordination)"). CODING_STANDARDS.md §3 fixes the prefixes
(``run_``, ``evt_``, ``stp_``) this module's ``new_*_id`` helpers use.

Generation is **monotonic** (the ULID spec's monotonicity clause): within
one millisecond the random component is incremented rather than redrawn,
so ids issued back-to-back always sort in issue order. The first id of a
millisecond still draws a fresh 80-bit random, so ids stay unguessable
and non-enumerable across milliseconds.

Real bug this fixes: with a fresh ``os.urandom`` per id, two events
emitted in the same millisecond sorted *randomly* against each other, so
"sortable by creation time" only held at millisecond granularity — and an
instrumented agent emits dozens of events per millisecond. Two things
broke. The Traces feed showed a single run's events shuffled
(…54, 52, 50, 53, 51…). Worse, the live firehose pages with
``WHERE event_id > cursor ORDER BY event_id``: an event persisted after
the cursor had advanced past its (smaller) id was skipped from the stream
permanently. Ordering has to be total for that cursor to be safe, so it
is established here, at the only place ids are minted.
"""

from __future__ import annotations

import os
import threading
import time

_CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # excludes I, L, O, U
_ULID_LENGTH = 26
_TIMESTAMP_BYTES = 6
_RANDOM_BYTES = 10
_MAX_RANDOM = (1 << (8 * _RANDOM_BYTES)) - 1

# Guards the monotonic counter below: events are emitted from whatever
# thread the agent runs on, so two threads can mint ids concurrently.
_lock = threading.Lock()
_last_timestamp_ms = -1
_last_random = 0


def new_ulid(*, timestamp_ms: int | None = None) -> str:
    """Generate a new ULID. ``timestamp_ms`` is injectable for tests only.

    Monotonic: two ids minted in the same millisecond sort in the order
    they were issued.
    """
    global _last_timestamp_ms, _last_random

    ts = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
    with _lock:
        # Only the same-millisecond case needs the counter. A different
        # timestamp — including a smaller one from an injected value or an
        # NTP step — redraws, so an explicitly passed timestamp is always
        # the one that lands in the id (the test seam stays honest, and a
        # backwards clock is no worse off than a plain ULID).
        if ts == _last_timestamp_ms and _last_random < _MAX_RANDOM:
            random_part = _last_random + 1
        else:
            random_part = int.from_bytes(os.urandom(_RANDOM_BYTES), "big")

        _last_timestamp_ms = ts
        _last_random = random_part

    payload = ts.to_bytes(_TIMESTAMP_BYTES, byteorder="big") + random_part.to_bytes(
        _RANDOM_BYTES, byteorder="big"
    )
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
