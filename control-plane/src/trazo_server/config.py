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
    # structlog output format (ARCHITECTURE.md §8): JSON in prod/containers,
    # human-readable console renderer for local dev.
    log_json: bool = True
