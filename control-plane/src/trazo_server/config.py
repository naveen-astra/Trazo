"""Environment-driven settings for the control plane (ARCHITECTURE section 6).

Every option has a ``TRAZO_``-prefixed env var, a documented default, and an
entry in ``deploy/.env.example``. Precedence: explicit kwargs > env > defaults.
"""

from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_API_KEY = "dev-change-me"

# Floors enforced only when environment == "production". Generated secrets
# (scripts/prod/init_env.py) clear them by a wide margin; they exist to stop
# a hand-edited placeholder from reaching a public host, not to grade
# entropy.
_MIN_SECRET_LEN = 32
_MIN_PASSWORD_LEN = 12


class Settings(BaseSettings):
    """Control-plane settings, read from ``TRAZO_*`` environment variables."""

    model_config = SettingsConfigDict(env_prefix="TRAZO_")

    # "production" turns on every launch safeguard at once: sign-in required
    # on read endpoints, secure cookies, API docs off, and a startup refusal
    # if any secret is missing, weak, or still a development default.
    environment: Literal["development", "production"] = "development"

    api_key: str = DEV_API_KEY
    # Setting a password is what turns dashboard sign-in on. In development
    # it is optional (unset keeps the local stack open, as it always was);
    # in production it is mandatory.
    dashboard_password: str | None = None
    # Signs session cookies. Rotating it signs every user out.
    session_secret: str | None = None
    session_ttl_hours: int = 12
    # Failed sign-in attempts allowed per client IP within the window before
    # further attempts are refused with 429.
    login_max_attempts: int = 5
    login_window_minutes: int = 15
    database_url: str = "postgresql://trazo:trazo@localhost:5432/trazo"
    redis_url: str = "redis://localhost:6379/0"
    opa_url: str = "http://localhost:8181"
    # Container default; matches deploy/docker-compose.yml's blobdata mount.
    blob_root: str = "/var/lib/trazo/blobs"
    # Container default; the actual exposure is controlled by compose port mapping.
    host: str = "0.0.0.0"
    port: int = 8420
    # Which peers may set X-Forwarded-For. Only widen this when the control
    # plane is reachable solely through a reverse proxy (the production
    # compose file keeps it off every published port) -- trusting the
    # header from the open internet would let any client choose the IP the
    # sign-in throttle attributes its attempts to.
    forwarded_allow_ips: str = "127.0.0.1"
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
    # Goal-drift detection (trazo_server.drift). Off by default: it needs a
    # model to judge with, and the judge's accuracy is the model's. Any
    # OpenAI-compatible endpoint works; a local Ollama costs nothing. There
    # is deliberately no default model: the 3B model tried first could not
    # tell clean runs from drifted ones (see
    # benchmark/detection/results-drift-qwen2.5-3b.md), so the operator has
    # to choose one and check it. In a container, "localhost" is the
    # container itself -- point drift_base_url at the host, e.g.
    # http://host.docker.internal:11434/v1.
    feature_drift_detector: bool = False
    drift_base_url: str = "http://localhost:11434/v1"
    drift_model: str = ""
    drift_api_key: str | None = None
    drift_every_n_llm_calls: int = 2
    drift_confirmations: int = 2
    drift_timeout_seconds: float = 30.0
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
    # non-permissive default without knowing it in advance. Production must
    # name its origin explicitly.
    cors_origins: str = "*"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def auth_required(self) -> bool:
        return self.dashboard_password is not None

    @property
    def session_cookie_name(self) -> str:
        # The __Host- prefix makes the browser enforce Secure, Path=/ and no
        # Domain attribute -- so no subdomain can plant or read it. Browsers
        # reject it over plain http, hence development's unprefixed name.
        return "__Host-trazo_session" if self.is_production else "trazo_session"

    @model_validator(mode="after")
    def _check_launch_safeguards(self) -> Self:
        if not self.is_production:
            if self.dashboard_password is not None and not self.session_secret:
                raise ValueError(
                    "TRAZO_SESSION_SECRET must be set whenever "
                    "TRAZO_DASHBOARD_PASSWORD is"
                )
            return self

        # Every problem at once, so a deploy is fixed in one edit rather
        # than one failed boot at a time.
        problems: list[str] = []
        if self.api_key == DEV_API_KEY or len(self.api_key) < _MIN_SECRET_LEN:
            problems.append(
                f"TRAZO_API_KEY must be a random value of at least {_MIN_SECRET_LEN} "
                "characters (not the development default)"
            )
        if (
            self.dashboard_password is None
            or len(self.dashboard_password) < _MIN_PASSWORD_LEN
        ):
            problems.append(
                "TRAZO_DASHBOARD_PASSWORD must be set, at least "
                f"{_MIN_PASSWORD_LEN} characters"
            )
        if not self.session_secret or len(self.session_secret) < _MIN_SECRET_LEN:
            problems.append(
                f"TRAZO_SESSION_SECRET must be at least {_MIN_SECRET_LEN} characters"
            )
        if self.cors_origins.strip() == "*":
            problems.append(
                "TRAZO_CORS_ORIGINS must name the dashboard origin, not '*'"
            )
        db_password = urlsplit(self.database_url).password or ""
        if db_password in ("", "trazo") or len(db_password) < 16:
            problems.append(
                "the database password in TRAZO_DATABASE_URL must be a random "
                "value of at least 16 characters (not the development default)"
            )
        if problems:
            raise ValueError(
                "refusing to start in production:\n  - " + "\n  - ".join(problems)
            )
        return self
