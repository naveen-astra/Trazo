"""Request-scoped structlog context (ARCHITECTURE.md §8: "request_id...
where applicable"). Binds a request_id to every log line emitted while
handling a request, and echoes it back as a response header for tracing
across services.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = structlog.get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Binds ``request_id`` (from ``X-Request-Id`` or freshly generated) to
    structlog's contextvars for the lifetime of one request/response cycle."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        structlog.contextvars.clear_contextvars()
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response
