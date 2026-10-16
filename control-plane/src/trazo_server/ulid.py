"""ULID generation for server-minted IDs (TRZ-P5-06).

Every ID the SDK mints is a ULID (CODING_STANDARDS.md §3: ``run_``,
``evt_``, ``stp_`` prefixes) via ``trazo.core.ulid`` — but ``sdk`` and
``control-plane`` never cross-import (DEVELOPMENT_GUIDE.md), so a
``detection.raised`` event minted server-side (the only event kind the
control plane itself originates) needs its own copy of the same tiny,
dependency-free generator. Kept byte-for-byte identical to
``sdk/src/trazo/core/ulid.py`` on purpose — same format, same sort
order, same "no library dependency" reasoning, and the same monotonic
generation: within one millisecond the random component is incremented
rather than redrawn, so ids issued back-to-back sort in issue order.

That matters here for the same reason it does in the SDK copy: these
``evt_`` ids land in the same ``events`` table and are streamed by the
same firehose, which pages with ``WHERE event_id > cursor``. An id that
sorted below an already-passed cursor would be skipped from the live
stream permanently.
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

_lock = threading.Lock()
_last_timestamp_ms = -1
_last_random = 0


def new_ulid(*, timestamp_ms: int | None = None) -> str:
    """Generate a new ULID. ``timestamp_ms`` is injectable for tests only.

    Monotonic: two ids minted in the same millisecond sort in the order
    they were issued.
    """
    global _last_timestamp_ms, _last_random

    with _lock:
        # The clock is read inside the lock. Read outside it, a thread could
        # take a reading, be preempted while another thread minted in the
        # next millisecond, and then -- seeing a timestamp different from
        # the last one issued -- draw a fresh random part that sorted below
        # ids already handed out.
        explicit = timestamp_ms is not None
        ts = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
        if not explicit and ts < _last_timestamp_ms:
            # A clock-derived reading never goes backwards: a stale reading
            # or an NTP step back stays in the last millisecond issued and
            # takes the counter path below, so ids remain strictly
            # increasing. (An explicitly passed timestamp is the test seam
            # and always lands unchanged.)
            ts = _last_timestamp_ms
        if ts == _last_timestamp_ms and _last_random < _MAX_RANDOM:
            random_part = _last_random + 1
        else:
            if ts == _last_timestamp_ms and not explicit:
                # The counter is exhausted within this millisecond: move to
                # the next one rather than redraw, which could sort lower.
                ts += 1
            random_part = int.from_bytes(os.urandom(_RANDOM_BYTES), "big")

        _last_timestamp_ms = ts
        _last_random = random_part

    payload = ts.to_bytes(_TIMESTAMP_BYTES, byteorder="big") + random_part.to_bytes(
        _RANDOM_BYTES, byteorder="big"
    )
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
