from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import get_logger
from app.core.request_context import REQUEST_ID_HEADER, current_request_id
from app.schemas.errors import ErrorBody, ErrorResponse

logger = get_logger(__name__)

INTERNAL_ERROR_MESSAGE = "An unexpected error occurred. Please try again later."
HTTP_ERROR_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    429: "too_many_requests",
    503: "service_unavailable",
}


class PulseError(Exception):
    """Base for errors PULSE raises on purpose. The message is shown to API clients."""

    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class DataValidationError(PulseError):
    """Input data (an import row, a payload, a parameter) breaks a business rule."""

    status_code = 422
    code = "validation_error"


class NotFoundError(PulseError):
    status_code = 404
    code = "not_found"


class ConnectorError(PulseError):
    """An external source such as Omerlo failed or returned something unusable."""

    status_code = 502
    code = "connector_error"

    def __init__(self, message: str, *, source: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details={**(details or {}), "source": source})
        self.source = source


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = current_request_id()
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, details=details, request_id=request_id)
    )
    headers = dict(headers or {})
    if request_id:
        headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(status_code=status_code, content=body.model_dump(), headers=headers)


async def handle_pulse_error(_request: Request, exc: PulseError) -> JSONResponse:
    if exc.status_code >= 500:
        logger.error("pulse_error", code=exc.code, error_message=exc.message, exc_info=exc)
    else:
        logger.warning("pulse_error", code=exc.code, error_message=exc.message)
    return error_response(exc.status_code, exc.code, exc.message, exc.details)


async def handle_http_exception(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code >= 500:
        logger.error("http_error", status_code=exc.status_code, exc_info=exc)
    return error_response(
        exc.status_code,
        HTTP_ERROR_CODES.get(exc.status_code, "http_error"),
        str(exc.detail),
        headers=exc.headers,
    )


async def handle_request_validation_error(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    # The rejected input is left out on purpose: it can contain personal data.
    errors = [
        {"location": list(error["loc"]), "message": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]
    logger.info("request_validation_failed", errors=errors)
    return error_response(422, "validation_error", "The request is invalid.", {"errors": errors})


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    _log_unhandled_error(request.method, request.url.path, exc)
    return error_response(500, "internal_error", INTERNAL_ERROR_MESSAGE)


def _log_unhandled_error(method: str, path: str, exc: Exception) -> None:
    logger.error("unhandled_error", method=method, path=path, exc_info=exc)


class UnhandledErrorMiddleware:
    """Turns unexpected errors into the standard 500 inside the CORS and header middleware.

    Starlette's own 500 handler runs outside every middleware, so its responses would lack
    CORS and security headers and browsers would block them.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_tracking_start(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_tracking_start)
        except Exception as exc:
            if response_started:
                raise
            _log_unhandled_error(scope["method"], scope["path"], exc)
            response = error_response(500, "internal_error", INTERNAL_ERROR_MESSAGE)
            await response(scope, receive, send_tracking_start)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(PulseError, handle_pulse_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(RequestValidationError, handle_request_validation_error)
    app.add_exception_handler(Exception, handle_unexpected_error)
