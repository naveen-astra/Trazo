"""Environment-driven settings for the control plane (ARCHITECTURE section 6).

Every option has a ``TRAZO_``-prefixed env var, a documented default, and an
entry in ``deploy/.env.example``. Precedence: explicit kwargs > env > defaults.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Control-plane settings, read from ``TRAZO_*`` environment variables."""

    model_config = SettingsConfigDict(env_prefix="TRAZO_")

    api_key: str = "dev-change-me"
    database_url: str = "postgresql://trazo:trazo@localhost:5432/trazo"
    redis_url: str = "redis://localhost:6379/0"
    opa_url: str = "http://localhost:8181"
    # Container default; matches deploy/docker-compose.yml's blobdata mount.
    blob_root: str = "/var/lib/trazo/blobs"
    # Container default; the actual exposure is controlled by compose port mapping.
    host: str = "0.0.0.0"
    port: int = 8420
    # Store worker: a 'running' run whose started_at is older than this
    # never got a run.finished — mark it 'stale' rather than leaving it
    # running forever (DATABASE.md §2 runs.status).
    stale_run_ttl_hours: int = 6
    # Feature flag (IMPLEMENTATION_PLAN.md §6): the store worker runs
    # in-process with the API (ARCHITECTURE.md §2.1), started from the app
    # lifespan. On by default for real deployment; tests that don't have a
    # real Redis/Postgres to poll set this False.
    feature_store_worker: bool = True
    # Feature flag (TRZ-P5-03/06): the detector worker, same in-process
    # background-task shape as the store worker above. On by default;
    # tests without a real Redis/Postgres to poll set this False.
    feature_detector_worker: bool = True
    # structlog output format (ARCHITECTURE.md §8): JSON in prod/containers,
    # human-readable console renderer for local dev.
    log_json: bool = True
    # CORS origins the dashboard is served from, comma-separated ("*" for
    # any). Query/dashboard endpoints are already documented as
    # unauthenticated-by-default, intended for localhost/trusted-network
    # only (ARCHITECTURE.md §5, ADR-009) -- CORS here controls which
    # *browser* origins may read them, not whether the API itself is
    # protected, and ingest/policy stay key-gated regardless of this
    # setting. Defaults permissive to match that already-documented
    # posture and because the dashboard's own port is user-configurable
    # (deploy/.env's DASHBOARD_PORT), so no single origin is a safe
    # non-permissive default without knowing it in advance.
    cors_origins: str = "*"
