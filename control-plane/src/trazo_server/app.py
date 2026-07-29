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
from prometheus_client import make_asgi_app
from redis.asyncio import Redis

from trazo_server import __version__
from trazo_server.api import ingest_router, live_router, query_router
from trazo_server.api.problem_details import register_problem_details_handlers
from trazo_server.bus.redis_streams import RedisStreamsBus
from trazo_server.config import Settings
from trazo_server.detectors.base import Detector
from trazo_server.detectors.budget import BudgetDetector
from trazo_server.detectors.loop import LoopDetector
from trazo_server.detectors.thrash import ThrashDetector
from trazo_server.logging import configure_logging
from trazo_server.middleware import RequestIDMiddleware
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
        redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
        event_bus = RedisStreamsBus(redis_client)
        trace_store = PostgresTraceStore(engine)
        app.state.engine = engine
        app.state.redis_client = redis_client
        app.state.event_bus = event_bus
        app.state.trace_store = trace_store
        app.state.blob_store = FilesystemBlobStore(Path(settings.blob_root))

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

    app = FastAPI(title="Trazo control plane", version=__version__, lifespan=lifespan)
    app.state.settings = settings

    app.add_middleware(RequestIDMiddleware)
    register_problem_details_handlers(app)
    app.include_router(ingest_router)
    app.include_router(query_router)
    app.include_router(live_router)

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

    app.mount("/metrics", make_asgi_app())

    return app
