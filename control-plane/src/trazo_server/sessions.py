"""Dashboard sign-in primitives: signed session tokens and a login throttle.

Tokens are stateless -- ``v1.<expires>.<nonce>.<signature>`` -- so a
restart or a second replica needs no shared session table. The signing
key is derived from both the session secret and the dashboard password,
which gives two revocation levers without any server-side state: rotating
``TRAZO_SESSION_SECRET`` or changing ``TRAZO_DASHBOARD_PASSWORD`` signs
everyone out.

Stdlib only; nothing here touches the network or the database.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections import OrderedDict, deque
from collections.abc import Callable

_VERSION = "v1"


def _signing_key(session_secret: str, password: str) -> bytes:
    password_digest = hashlib.sha256(password.encode("utf-8")).digest()
    return hmac.new(
        session_secret.encode("utf-8"),
        b"trazo-session-v1\x00" + password_digest,
        hashlib.sha256,
    ).digest()


def _sign(key: bytes, message: str) -> str:
    digest = hmac.new(key, message.encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def issue_token(
    *,
    session_secret: str,
    password: str,
    ttl_seconds: int,
    now: float | None = None,
) -> str:
    expires = int((time.time() if now is None else now) + ttl_seconds)
    body = f"{_VERSION}.{expires}.{secrets.token_urlsafe(16)}"
    return f"{body}.{_sign(_signing_key(session_secret, password), body)}"


def verify_token(
    token: str,
    *,
    session_secret: str,
    password: str,
    now: float | None = None,
) -> bool:
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != _VERSION:
        return False
    body, signature = ".".join(parts[:3]), parts[3]
    expected = _sign(_signing_key(session_secret, password), body)
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        expires = int(parts[1])
    except ValueError:
        return False
    return expires > (time.time() if now is None else now)


def passwords_match(supplied: str, expected: str) -> bool:
    """Constant-time comparison that also hides the expected length."""
    return hmac.compare_digest(
        hashlib.sha256(supplied.encode("utf-8")).digest(),
        hashlib.sha256(expected.encode("utf-8")).digest(),
    )


class LoginThrottle:
    """Per-client limit on *failed* sign-in attempts in a sliding window.

    In-process by design: the control plane runs as a single replica
    (ARCHITECTURE.md §2.1), and keeping this out of Redis means a Redis
    outage cannot turn into "sign-in rejects everyone". Only failures
    count, so a correct password is never locked out by past typos from a
    different client.
    """

    # Bounds memory against an attacker cycling source addresses; the
    # oldest-tracked client is forgotten first.
    _MAX_TRACKED_CLIENTS = 10_000

    def __init__(
        self,
        *,
        max_attempts: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_attempts = max_attempts
        self._window = window_seconds
        self._clock = clock
        self._failures: OrderedDict[str, deque[float]] = OrderedDict()

    def _prune(self, client: str) -> deque[float]:
        attempts = self._failures.get(client)
        if attempts is None:
            return deque()
        cutoff = self._clock() - self._window
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if not attempts:
            del self._failures[client]
        return attempts

    def retry_after(self, client: str) -> int | None:
        """Seconds until ``client`` may try again, or None if it may now."""
        attempts = self._prune(client)
        if len(attempts) < self._max_attempts:
            return None
        return max(1, int(attempts[0] + self._window - self._clock()) + 1)

    def record_failure(self, client: str) -> None:
        attempts = self._failures.setdefault(client, deque())
        self._failures.move_to_end(client)
        attempts.append(self._clock())
        while len(self._failures) > self._MAX_TRACKED_CLIENTS:
            self._failures.popitem(last=False)

    def reset(self, client: str) -> None:
        self._failures.pop(client, None)
