"""FastAPI dependency providers: bearer-key auth and shared resources.

Resources (event bus, blob store) are constructed once in app.py's
create_app and hung off ``app.state``; these functions just narrow the
type for route handlers (Starlette's State has no static typing of its
own).
"""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Header, Request

from trazo_server.api.problem_details import ProblemDetailsError
from trazo_server.bus.protocol import EventBus
from trazo_server.config import Settings
from trazo_server.policy.opa_client import OpaClient
from trazo_server.sessions import verify_token
from trazo_server.store.blob_store import BlobStore
from trazo_server.store.trace_store import TraceStore


def _bearer_is_valid(settings: Settings, authorization: str | None) -> bool:
    # compare_digest, not ==: a byte-by-byte early exit leaks how much of a
    # guessed key was right through response timing.
    return authorization is not None and hmac.compare_digest(
        authorization.encode("utf-8"), f"Bearer {settings.api_key}".encode()
    )


def has_valid_session(request: Request) -> bool:
    settings: Settings = request.app.state.settings
    token = request.cookies.get(settings.session_cookie_name)
    if not token or settings.dashboard_password is None or not settings.session_secret:
        return False
    return verify_token(
        token,
        session_secret=settings.session_secret,
        password=settings.dashboard_password,
    )


async def require_api_key(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> None:
    """Bearer-key auth for ingest/policy endpoints (ADR-009, API_SPEC.md)."""
    if not _bearer_is_valid(request.app.state.settings, authorization):
        raise ProblemDetailsError(
            status=401,
            title="Unauthorized",
            detail="missing or invalid bearer API key",
        )


async def require_viewer(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> None:
    """Read access: a signed-in dashboard session, or the API key.

    The key is accepted too because the SDK and CLI read through these
    same endpoints (``trazo replay`` fetches bundles and blobs, ``trazo
    tail`` streams a run) and have no browser session to present. A no-op
    unless sign-in is configured, so a local development stack stays open.
    """
    settings: Settings = request.app.state.settings
    if not settings.auth_required:
        return
    if _bearer_is_valid(settings, authorization) or has_valid_session(request):
        return
    raise ProblemDetailsError(
        status=401,
        title="Unauthorized",
        detail="sign in to the dashboard, or send the API key as a bearer token",
    )


def get_event_bus(request: Request) -> EventBus:
    bus: EventBus = request.app.state.event_bus
    return bus


def get_blob_store(request: Request) -> BlobStore:
    store: BlobStore = request.app.state.blob_store
    return store


def get_trace_store(request: Request) -> TraceStore:
    store: TraceStore = request.app.state.trace_store
    return store


def get_opa_client(request: Request) -> OpaClient:
    client: OpaClient = request.app.state.opa_client
    return client
