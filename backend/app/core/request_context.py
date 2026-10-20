import re
import time
import uuid

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import get_logger

REQUEST_ID_HEADER = "X-Request-ID"
# Incoming ids end up in logs and response headers, so only plain tokens are trusted.
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")

logger = get_logger(__name__)


class RequestContextMiddleware:
    """Gives every HTTP request an id, binds it to the logs and logs the outcome."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id_from(scope)
        # Not reset when the request ends: the 500 handler runs after this middleware
        # has unwound and still needs the id. Clearing first keeps requests separate.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        status_code = 500
        started = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            logger.info(
                "request_completed",
                method=scope["method"],
                path=scope["path"],
                status_code=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )


def current_request_id() -> str | None:
    return structlog.contextvars.get_contextvars().get("request_id")


def _request_id_from(scope: Scope) -> str:
    for name, value in scope["headers"]:
        if name == b"x-request-id":
            candidate = value.decode("latin-1")
            if _SAFE_REQUEST_ID.fullmatch(candidate):
                return candidate
    return uuid.uuid4().hex
