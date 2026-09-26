"""Dashboard sign-in, read-endpoint protection, and production safeguards."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from trazo_server.api.deps import get_trace_store
from trazo_server.app import create_app
from trazo_server.config import Settings
from trazo_server.sessions import (
    LoginThrottle,
    issue_token,
    passwords_match,
    verify_token,
)
from trazo_server.store.memory_trace_store import InMemoryTraceStore

_PASSWORD = "correct-horse-battery"
_SECRET = "s" * 48
_API_KEY = "k" * 48

_STRONG_PROD = {
    "environment": "production",
    "api_key": _API_KEY,
    "dashboard_password": _PASSWORD,
    "session_secret": _SECRET,
    "cors_origins": "https://trazo.example.com",
    "database_url": "postgresql://trazo:" + "p" * 24 + "@postgres:5432/trazo",
}


def _client(tmp_path: Path, **overrides: object) -> TestClient:
    settings = Settings(
        blob_root=str(tmp_path / "blobs"),
        feature_store_worker=False,
        feature_detector_worker=False,
        **overrides,  # type: ignore[arg-type]
    )
    app = create_app(settings)
    store = InMemoryTraceStore()
    app.dependency_overrides[get_trace_store] = lambda: store
    base_url = "https://testserver" if settings.is_production else "http://testserver"
    return TestClient(app, base_url=base_url)


@pytest.fixture
def secured(tmp_path: Path) -> Iterator[TestClient]:
    with _client(
        tmp_path,
        api_key=_API_KEY,
        dashboard_password=_PASSWORD,
        session_secret=_SECRET,
        login_max_attempts=3,
    ) as client:
        yield client


@pytest.fixture
def open_dev(tmp_path: Path) -> Iterator[TestClient]:
    with _client(tmp_path) as client:
        yield client


def _login(client: TestClient, password: str = _PASSWORD) -> int:
    return client.post("/v1/auth/login", json={"password": password}).status_code


# --- settings -------------------------------------------------------------


def test_production__refuses_development_defaults_and_lists_every_problem() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(environment="production")

    message = str(exc_info.value)
    for fragment in (
        "TRAZO_API_KEY",
        "TRAZO_DASHBOARD_PASSWORD",
        "TRAZO_SESSION_SECRET",
        "TRAZO_CORS_ORIGINS",
        "database password",
    ):
        assert fragment in message


def test_production__accepts_strong_configuration() -> None:
    settings = Settings(**_STRONG_PROD)  # type: ignore[arg-type]

    assert settings.is_production
    assert settings.auth_required
    assert settings.session_cookie_name == "__Host-trazo_session"


def test_password_without_session_secret_is_rejected_even_in_development() -> None:
    with pytest.raises(ValidationError, match="TRAZO_SESSION_SECRET"):
        Settings(dashboard_password=_PASSWORD)


# --- tokens ---------------------------------------------------------------


def test_token__round_trips() -> None:
    token = issue_token(session_secret=_SECRET, password=_PASSWORD, ttl_seconds=60)

    assert verify_token(token, session_secret=_SECRET, password=_PASSWORD)


def test_token__rejects_a_tampered_expiry() -> None:
    token = issue_token(session_secret=_SECRET, password=_PASSWORD, ttl_seconds=60)
    version, expires, nonce, signature = token.split(".")
    forged = ".".join([version, str(int(expires) + 10**6), nonce, signature])

    assert not verify_token(forged, session_secret=_SECRET, password=_PASSWORD)


def test_token__rejects_an_expired_token() -> None:
    token = issue_token(
        session_secret=_SECRET, password=_PASSWORD, ttl_seconds=60, now=1_000.0
    )

    assert not verify_token(
        token, session_secret=_SECRET, password=_PASSWORD, now=1_061.0
    )


def test_token__changing_the_password_signs_everyone_out() -> None:
    token = issue_token(session_secret=_SECRET, password=_PASSWORD, ttl_seconds=60)

    assert not verify_token(token, session_secret=_SECRET, password="a-new-password")


def test_token__rotating_the_secret_signs_everyone_out() -> None:
    token = issue_token(session_secret=_SECRET, password=_PASSWORD, ttl_seconds=60)

    assert not verify_token(token, session_secret="t" * 48, password=_PASSWORD)


@pytest.mark.parametrize("junk", ["", "v1", "v1.x.y.z", "v2.1.2.3", "a.b.c.d.e"])
def test_token__rejects_malformed_input(junk: str) -> None:
    assert not verify_token(junk, session_secret=_SECRET, password=_PASSWORD)


def test_passwords_match() -> None:
    assert passwords_match(_PASSWORD, _PASSWORD)
    assert not passwords_match(_PASSWORD + "x", _PASSWORD)
    assert not passwords_match("", _PASSWORD)


# --- throttle -------------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_throttle__blocks_after_max_failures_and_recovers_after_the_window() -> None:
    clock = _Clock()
    throttle = LoginThrottle(max_attempts=3, window_seconds=60, clock=clock)

    for _ in range(3):
        assert throttle.retry_after("1.2.3.4") is None
        throttle.record_failure("1.2.3.4")

    assert throttle.retry_after("1.2.3.4") is not None
    assert throttle.retry_after("5.6.7.8") is None  # other clients unaffected

    clock.now = 61.0
    assert throttle.retry_after("1.2.3.4") is None


def test_throttle__reset_forgets_past_failures() -> None:
    throttle = LoginThrottle(max_attempts=2, window_seconds=60)
    throttle.record_failure("c")
    throttle.record_failure("c")

    throttle.reset("c")

    assert throttle.retry_after("c") is None


def test_throttle__bounds_how_many_clients_it_remembers() -> None:
    throttle = LoginThrottle(max_attempts=1, window_seconds=60)
    throttle._MAX_TRACKED_CLIENTS = 3  # type: ignore[misc]

    for client in ("a", "b", "c", "d"):
        throttle.record_failure(client)

    assert throttle.retry_after("a") is None  # evicted, oldest first
    assert throttle.retry_after("d") is not None


# --- API, sign-in configured ---------------------------------------------


def test_read_endpoints_require_sign_in(secured: TestClient) -> None:
    response = secured.get("/v1/runs")

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"


def test_live_stream_requires_sign_in(secured: TestClient) -> None:
    assert secured.get("/v1/live/firehose").status_code == 401


def test_session_reports_signed_out_then_signed_in(secured: TestClient) -> None:
    assert secured.get("/v1/auth/session").json() == {
        "auth_required": True,
        "authenticated": False,
    }

    assert _login(secured) == 204

    assert secured.get("/v1/auth/session").json() == {
        "auth_required": True,
        "authenticated": True,
    }
    assert secured.get("/v1/runs").status_code == 200


def test_login_cookie_is_httponly_and_strict(secured: TestClient) -> None:
    response = secured.post("/v1/auth/login", json={"password": _PASSWORD})

    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert response.headers["cache-control"] == "no-store"


def test_wrong_password_is_rejected(secured: TestClient) -> None:
    assert _login(secured, "not-the-password") == 401
    assert secured.get("/v1/runs").status_code == 401


def test_api_key_is_accepted_on_read_endpoints(secured: TestClient) -> None:
    response = secured.get("/v1/runs", headers={"Authorization": f"Bearer {_API_KEY}"})

    assert response.status_code == 200


def test_a_session_does_not_grant_ingest(secured: TestClient) -> None:
    """Write paths stay key-only: a browser session must not be able to
    push events or evaluate policy, only read."""
    assert _login(secured) == 204

    response = secured.post("/v1/ingest/events", json={"events": []})

    assert response.status_code == 401


def test_logout_ends_the_session(secured: TestClient) -> None:
    assert _login(secured) == 204

    assert secured.post("/v1/auth/logout").status_code == 204

    assert secured.get("/v1/runs").status_code == 401


def test_repeated_failures_are_throttled_even_for_the_right_password(
    secured: TestClient,
) -> None:
    for _ in range(3):
        assert _login(secured, "wrong") == 401

    response = secured.post("/v1/auth/login", json={"password": _PASSWORD})

    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0


def test_health_stays_public(secured: TestClient) -> None:
    assert secured.get("/healthz").status_code == 200


# --- API, sign-in not configured (local development) ---------------------


def test_development_without_a_password_stays_open(open_dev: TestClient) -> None:
    assert open_dev.get("/v1/runs").status_code == 200
    assert open_dev.get("/v1/auth/session").json() == {
        "auth_required": False,
        "authenticated": True,
    }


def test_login_is_refused_when_sign_in_is_not_enabled(open_dev: TestClient) -> None:
    assert _login(open_dev) == 400


# --- production app -------------------------------------------------------


def test_production_hides_api_docs(tmp_path: Path) -> None:
    with _client(tmp_path, **_STRONG_PROD) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404


def test_production_cookie_is_secure_and_host_prefixed(tmp_path: Path) -> None:
    with _client(tmp_path, **_STRONG_PROD) as client:
        response = client.post("/v1/auth/login", json={"password": _PASSWORD})

        cookie = response.headers["set-cookie"]
        assert cookie.startswith("__Host-trazo_session=")
        assert "secure" in cookie.lower()
        assert client.get("/v1/runs").status_code == 200


def test_production__lists_every_problem_even_when_a_password_is_set() -> None:
    """A half-configured deploy (password present, secret missing) used to
    stop at the first check, so fixing it took one failed boot per problem."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(environment="production", dashboard_password="short")

    message = str(exc_info.value)
    for fragment in (
        "TRAZO_API_KEY",
        "TRAZO_DASHBOARD_PASSWORD",
        "TRAZO_SESSION_SECRET",
    ):
        assert fragment in message


def test_main__exits_with_a_readable_message_on_bad_production_config(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from trazo_server.__main__ import main

    monkeypatch.setenv("TRAZO_ENVIRONMENT", "production")

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "invalid configuration" in err
    assert "TRAZO_API_KEY" in err
    assert "Traceback" not in err
