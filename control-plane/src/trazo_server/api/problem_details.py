"""RFC 9457 problem-details errors, the control plane's one error shape
(API_SPEC.md, ARCHITECTURE.md §7): ``{type, title, status, detail}`` on
every 4xx/5xx, including FastAPI's own validation and HTTP errors.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from trazo_server.errors import TrazoServerError

_MEDIA_TYPE = "application/problem+json"


class ProblemDetailsError(TrazoServerError):
    """Raise from a route/dependency to produce an RFC 9457 error response."""

    def __init__(
        self,
        *,
        status: int,
        title: str,
        detail: str,
        type_: str = "about:blank",
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.title = title
        self.detail = detail
        self.type = type_
        self.headers = headers or {}

    def to_body(self) -> dict[str, object]:
        return {
            "type": self.type,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
        }


def register_problem_details_handlers(app: FastAPI) -> None:
    """Install the three handlers that make every control-plane error a
    problem-details JSON body: our own ProblemDetailsError, FastAPI's
    request-validation errors, and Starlette's generic HTTPException."""

    @app.exception_handler(ProblemDetailsError)
    async def _handle_problem_details(
        request: Request, exc: ProblemDetailsError
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=exc.status,
            content=exc.to_body(),
            media_type=_MEDIA_TYPE,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        del request
        body = {
            "type": "about:blank",
            "title": "Request Validation Error",
            "status": 422,
            "detail": str(exc),
        }
        return JSONResponse(status_code=422, content=body, media_type=_MEDIA_TYPE)

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        del request
        title = exc.detail if isinstance(exc.detail, str) else "HTTP Error"
        body = {
            "type": "about:blank",
            "title": title,
            "status": exc.status_code,
            "detail": title,
        }
        return JSONResponse(
            status_code=exc.status_code, content=body, media_type=_MEDIA_TYPE
        )
