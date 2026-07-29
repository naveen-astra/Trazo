"""FastAPI dependency providers: bearer-key auth and shared resources.

Resources (event bus, blob store) are constructed once in app.py's
create_app and hung off ``app.state``; these functions just narrow the
type for route handlers (Starlette's State has no static typing of its
own).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Header, Request

from trazo_server.api.problem_details import ProblemDetailsError
from trazo_server.bus.protocol import EventBus
from trazo_server.policy.opa_client import OpaClient
from trazo_server.store.blob_store import BlobStore
from trazo_server.store.trace_store import TraceStore


async def require_api_key(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> None:
    """Bearer-key auth for ingest/policy endpoints (ADR-009, API_SPEC.md)."""
    settings = request.app.state.settings
    if authorization != f"Bearer {settings.api_key}":
        raise ProblemDetailsError(
            status=401,
            title="Unauthorized",
            detail="missing or invalid bearer API key",
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
