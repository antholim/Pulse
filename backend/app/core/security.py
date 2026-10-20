import os

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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


def cors_origins() -> list[str]:
    """Frontend origins allowed to call the API, from the comma-separated CORS_ORIGINS."""
    raw = os.environ.get("CORS_ORIGINS") or DEFAULT_CORS_ORIGINS
    origins = [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]
    # With credentials allowed, a wildcard would let any site make authenticated calls.
    if "*" in origins:
        raise ValueError("CORS_ORIGINS must list explicit origins, not '*'")
    return origins
