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
    # Container default; the actual exposure is controlled by compose port mapping.
    host: str = "0.0.0.0"
    port: int = 8420
