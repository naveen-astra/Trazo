"""HTTP API routers (API_SPEC.md): auth, ingest, query, live, policy."""

from trazo_server.api.auth import router as auth_router
from trazo_server.api.ingest import router as ingest_router
from trazo_server.api.live import router as live_router
from trazo_server.api.policy import router as policy_router
from trazo_server.api.query import router as query_router

__all__ = [
    "auth_router",
    "ingest_router",
    "live_router",
    "policy_router",
    "query_router",
]
