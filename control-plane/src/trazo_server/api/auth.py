"""Dashboard sign-in: ``/v1/auth/session``, ``/v1/auth/login``, ``/v1/auth/logout``.

One shared password (``TRAZO_DASHBOARD_PASSWORD``) guards the read side
of the API for browsers; a successful sign-in sets an HttpOnly,
SameSite=Strict session cookie that the dashboard's same-origin requests
(fetch and EventSource alike) carry automatically. Per-user accounts are
a roadmap item; this is the honest single-team version of the same
boundary.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from trazo_server.api.deps import has_valid_session
from trazo_server.api.problem_details import ProblemDetailsError
from trazo_server.config import Settings
from trazo_server.sessions import LoginThrottle, issue_token, passwords_match

router = APIRouter(prefix="/v1/auth")

_NO_STORE = {"Cache-Control": "no-store"}


class SessionOut(BaseModel):
    auth_required: bool
    authenticated: bool


class LoginIn(BaseModel):
    # Bounded so a multi-megabyte "password" can't be used to make the
    # server hash large inputs on every attempt.
    password: str = Field(min_length=1, max_length=512)


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _throttle(request: Request) -> LoginThrottle:
    throttle: LoginThrottle = request.app.state.login_throttle
    return throttle


def _client_key(request: Request) -> str:
    # The real client address: uvicorn rewrites request.client from the
    # reverse proxy's X-Forwarded-For (see __main__.py). Without that this
    # would be the proxy's own address, and one bad actor would lock out
    # every visitor at once.
    return request.client.host if request.client else "unknown"


@router.get("/session", response_model=SessionOut)
async def get_session(request: Request, response: Response) -> SessionOut:
    response.headers.update(_NO_STORE)
    settings = _settings(request)
    return SessionOut(
        auth_required=settings.auth_required,
        authenticated=(not settings.auth_required) or has_valid_session(request),
    )


@router.post("/login", status_code=204)
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    throttle: Annotated[LoginThrottle, Depends(_throttle)],
) -> None:
    settings = _settings(request)
    if settings.dashboard_password is None or settings.session_secret is None:
        raise ProblemDetailsError(
            status=400,
            title="Sign-in Not Enabled",
            detail="this deployment has no dashboard password configured",
        )

    client = _client_key(request)
    retry_after = throttle.retry_after(client)
    if retry_after is not None:
        raise ProblemDetailsError(
            status=429,
            title="Too Many Attempts",
            detail=(
                f"too many failed sign-in attempts; try again in {retry_after} seconds"
            ),
            headers={"Retry-After": str(retry_after), **_NO_STORE},
        )

    if not passwords_match(body.password, settings.dashboard_password):
        throttle.record_failure(client)
        raise ProblemDetailsError(
            status=401,
            title="Unauthorized",
            detail="incorrect password",
            headers=_NO_STORE,
        )

    throttle.reset(client)
    ttl_seconds = settings.session_ttl_hours * 3600
    response.headers.update(_NO_STORE)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=issue_token(
            session_secret=settings.session_secret,
            password=settings.dashboard_password,
            ttl_seconds=ttl_seconds,
        ),
        max_age=ttl_seconds,
        path="/",
        httponly=True,
        secure=settings.is_production,
        samesite="strict",
    )


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response) -> None:
    settings = _settings(request)
    response.headers.update(_NO_STORE)
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.is_production,
        samesite="strict",
    )
