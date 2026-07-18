"""FastAPI application factory (Phase 0 stub).

Serves the three ops endpoints required by ARCHITECTURE section 8:
``/healthz`` (liveness), ``/readyz`` (readiness), and ``/metrics``
(Prometheus). ``/readyz`` returns static readiness until the Postgres and
Redis clients exist; the real dependency checks land with TRZ-P1-03/04.
"""

from typing import Any

from fastapi import FastAPI
from prometheus_client import make_asgi_app

from trazo_server import __version__
from trazo_server.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the control-plane ASGI app with the given (or env-derived) settings."""
    settings = settings or Settings()
    app = FastAPI(title="Trazo control plane", version=__version__)
    app.state.settings = settings

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/readyz")
    async def readyz() -> dict[str, Any]:
        # Stub: real checks (Postgres, Redis reachable) arrive with the
        # store and bus implementations in Phase 1.
        checks = {"postgres": "stubbed", "redis": "stubbed"}
        return {"status": "ready", "checks": checks}

    app.mount("/metrics", make_asgi_app())

    return app
