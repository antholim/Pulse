import os

from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import error_response

# Added to every response unless the route already set the header.
# Strict-Transport-Security is ignored by browsers over plain HTTP, so it only takes
# effect once the API is served over HTTPS (Fly.io, #65).
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=31536000",
}

DEFAULT_CORS_ORIGINS = "http://localhost:5173"
DEFAULT_MAX_REQUEST_BYTES = 10 * 1024 * 1024


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RequestSizeLimitMiddleware:
    """Answers 413 to request bodies over max_bytes, whether or not they send Content-Length."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = Headers(scope=scope).get("content-length", "")
        if declared.isdigit() and int(declared) > self.max_bytes:
            response = error_response(413, "payload_too_large", self._message())
            await response(scope, receive, send)
            return

        received = 0

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Raised inside the app, so the usual HTTP error handler formats it.
                    raise HTTPException(413, self._message())
            return message

        await self.app(scope, counting_receive, send)

    def _message(self) -> str:
        return f"The request body is over {self.max_bytes} bytes."


def max_request_bytes() -> int:
    """Largest request body the API accepts, from MAX_REQUEST_BYTES."""
    raw = os.environ.get("MAX_REQUEST_BYTES")
    value = int(raw) if raw else DEFAULT_MAX_REQUEST_BYTES
    if value <= 0:
        raise ValueError("MAX_REQUEST_BYTES must be a positive number of bytes")
    return value


def cors_origins() -> list[str]:
    """Frontend origins allowed to call the API, from the comma-separated CORS_ORIGINS."""
    raw = os.environ.get("CORS_ORIGINS") or DEFAULT_CORS_ORIGINS
    origins = [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]
    # With credentials allowed, a wildcard would let any site make authenticated calls.
    if "*" in origins:
        raise ValueError("CORS_ORIGINS must list explicit origins, not '*'")
    return origins
