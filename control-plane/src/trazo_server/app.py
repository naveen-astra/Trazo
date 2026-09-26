"""FastAPI application factory.

Serves the three ops endpoints required by ARCHITECTURE section 8:
``/healthz`` (liveness), ``/readyz`` (readiness — checks Postgres + Redis),
and ``/metrics`` (Prometheus); mounts the API routers (API_SPEC.md) and the
structlog request_id / metrics baseline (TRZ-P1-08).
"""

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis.asyncio import Redis

from trazo_server import __version__
from trazo_server.api import (
    auth_router,
    ingest_router,
    live_router,
    policy_router,
    query_router,
)
from trazo_server.api.problem_details import register_problem_details_handlers
from trazo_server.bus.protocol import BUS_SOCKET_TIMEOUT_SECONDS
from trazo_server.bus.redis_streams import RedisStreamsBus
from trazo_server.config import Settings
from trazo_server.detectors.base import Detector
from trazo_server.detectors.budget import BudgetDetector
from trazo_server.detectors.loop import LoopDetector
from trazo_server.detectors.thrash import ThrashDetector
from trazo_server.logging import configure_logging
from trazo_server.middleware import RequestIDMiddleware
from trazo_server.policy.opa_client import HttpOpaClient
from trazo_server.sessions import LoginThrottle
from trazo_server.store.blob_fs import FilesystemBlobStore
from trazo_server.store.engine import create_engine
from trazo_server.store.postgres_trace_store import PostgresTraceStore
from trazo_server.workers.detection_persistence import PersistDetection
from trazo_server.workers.detector_worker import DetectorWorker
from trazo_server.workers.store_worker import StoreWorker

_READYZ_TIMEOUT_SECONDS = 2.0


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the control-plane ASGI app with the given (or env-derived) settings."""
    settings = settings or Settings()
    configure_logging(json_logs=settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Constructing these is lazy for both drivers (asyncpg, redis-py):
        # no connection is opened until first use, so this is safe even
        # when Postgres/Redis aren't reachable yet (e.g. under TestClient).
        engine = create_engine(settings.database_url)
        # socket_timeout is set explicitly, and deliberately above the
        # workers' XREADGROUP block (BUS_SOCKET_TIMEOUT_SECONDS), because the two
        # race: the block is a server-side wait, the socket timeout is the
        # client's patience for the reply to that same command. redis-py
        # 8 defaults socket_timeout to 5s and the workers block for
        # exactly 5s, so every idle poll lost the race and raised
        # TimeoutError — and when Redis *did* deliver a batch at that
        # boundary it recorded the messages in the group's pending list
        # while the client never read the response, stranding them.
        # Observed live: store-worker wedged with 167 pending, unacked
        # messages and nothing persisting at all.
        redis_client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=BUS_SOCKET_TIMEOUT_SECONDS,
        )
        event_bus = RedisStreamsBus(redis_client)
        trace_store = PostgresTraceStore(engine)
        app.state.engine = engine
        app.state.redis_client = redis_client
        app.state.event_bus = event_bus
        app.state.trace_store = trace_store
        app.state.blob_store = FilesystemBlobStore(Path(settings.blob_root))
        app.state.opa_client = HttpOpaClient(base_url=settings.opa_url)

        worker_task: asyncio.Task[None] | None = None
        if settings.feature_store_worker:
            worker = StoreWorker(
                bus=event_bus,
                trace_store=trace_store,
                blob_store=app.state.blob_store,
                consumer_name=f"store-worker-{socket.gethostname()}-{id(app)}",
                stale_run_ttl=timedelta(hours=settings.stale_run_ttl_hours),
            )
            worker_task = asyncio.create_task(worker.run_forever())

        detector_worker_task: asyncio.Task[None] | None = None
        if settings.feature_detector_worker:
            detectors: list[Detector] = [
                LoopDetector(),
                BudgetDetector(),
                ThrashDetector(),
            ]
            detector_worker = DetectorWorker(
                bus=event_bus,
                trace_store=trace_store,
                detectors=detectors,
                consumer_name=f"detector-worker-{socket.gethostname()}-{id(app)}",
                on_detection=PersistDetection(trace_store=trace_store, bus=event_bus),
            )
            detector_worker_task = asyncio.create_task(detector_worker.run_forever())

        try:
            yield
        finally:
            if worker_task is not None:
                worker_task.cancel()
                with suppress(asyncio.CancelledError):
                    await worker_task
            if detector_worker_task is not None:
                detector_worker_task.cancel()
                with suppress(asyncio.CancelledError):
                    await detector_worker_task
            await redis_client.aclose()
            await engine.dispose()
            await app.state.opa_client.aclose()

    # Interactive docs and the schema are a reconnaissance map of every
    # endpoint; a public production host has no business serving them.
    docs_enabled = not settings.is_production
    app = FastAPI(
        title="Trazo control plane",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.state.settings = settings
    app.state.login_throttle = LoginThrottle(
        max_attempts=settings.login_max_attempts,
        window_seconds=settings.login_window_minutes * 60,
    )

    app.add_middleware(RequestIDMiddleware)
    # Outermost (added last -- Starlette wraps in reverse order of
    # add_middleware calls), so a browser's OPTIONS preflight gets a CORS
    # response before reaching anything else. No CORS middleware at all
    # was the actual bug behind the dashboard's live-browser verification
    # never having been done against the real compose stack (ROADMAP.md's
    # own P2 footnote: only a stdlib mock control plane, same-origin,
    # never hit this) -- confirmed directly: a real preflight against this
    # app returned 405, not a CORS response, before this fix.
    cors_origins = (
        settings.cors_origins.split(",") if settings.cors_origins != "*" else ["*"]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_problem_details_handlers(app)
    app.include_router(auth_router)
    app.include_router(ingest_router)
    app.include_router(query_router)
    app.include_router(live_router)
    app.include_router(policy_router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/readyz")
    async def readyz(response: Response) -> dict[str, Any]:
        checks: dict[str, str] = {}

        try:
            async with asyncio.timeout(_READYZ_TIMEOUT_SECONDS):
                async with app.state.engine.connect() as conn:
                    await conn.execute(sa.text("SELECT 1"))
            checks["postgres"] = "ok"
        except Exception:
            checks["postgres"] = "error"

        try:
            async with asyncio.timeout(_READYZ_TIMEOUT_SECONDS):
                await app.state.redis_client.ping()
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "error"

        ready = all(v == "ok" for v in checks.values())
        if not ready:
            response.status_code = 503
        return {"status": "ready" if ready else "not_ready", "checks": checks}

    # A route, not app.mount("/metrics", ...): mounting makes Starlette
    # answer the documented path (API_SPEC.md §"GET /metrics") with a 307
    # to the trailing-slash form, so the endpoint the docs name serves no
    # body of its own. Prometheus follows redirects, which is why this
    # went unnoticed — but any client that doesn't gets nothing, as
    # scripts/smoke/phase1.sh's plain `curl -fsS /metrics` did.
    # FastAPI's own redirect_slashes still points /metrics/ back here, so
    # anything already scraping the trailing-slash form keeps working.
    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app
