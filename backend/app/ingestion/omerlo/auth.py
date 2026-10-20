"""OAuth 2 client credentials authentication for the Omerlo Reader API.

Every request to the Reader API needs `Authorization: Bearer <token>` and
`x-omerlo-media-id: <media id>`. `OmerloAuth` adds both, fetches a token on
first use, reuses it until shortly before it expires, and fetches a new one
after a 401 before retrying the request once.

The token request is sent through the same `httpx.Client` as the API call
(httpx's own DigestAuth works the same way), so one client handles everything.
"""

import logging
import math
import threading
import time
from collections.abc import AsyncGenerator, Callable, Generator

import httpx

from app.ingestion.omerlo.settings import OmerloSettings

logger = logging.getLogger(__name__)

MEDIA_ID_HEADER = "x-omerlo-media-id"


class OmerloAuthError(Exception):
    """The Omerlo token endpoint refused the credentials or returned an unusable response."""


class OmerloAuth(httpx.Auth):
    """Sync only: use it with `httpx.Client`.

    The lock is held while the token request is in flight. That is right for threads,
    but under `httpx.AsyncClient` a second coroutine would block on it and freeze the
    event loop, so async use is refused.
    """

    # Token responses must be read to get the access token.
    requires_response_body = True

    def __init__(self, settings: OmerloSettings, clock: Callable[[], float] = time.monotonic):
        self._settings = settings
        self._clock = clock
        self._lock = threading.Lock()
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._refresh_at = 0.0

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        with self._lock:
            if not self._has_valid_token():
                yield from self._fetch_token()
            token = self._access_token

        self._sign(request, token)
        response = yield request
        if response.status_code != httpx.codes.UNAUTHORIZED:
            return

        with self._lock:
            # Another thread may already have replaced the rejected token.
            if self._access_token == token:
                self._access_token = None
                yield from self._fetch_token()
            token = self._access_token

        self._sign(request, token)
        yield request

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        raise NotImplementedError("OmerloAuth only supports httpx.Client, not httpx.AsyncClient")
        yield request  # unreachable; keeps this an async generator, as httpx expects

    def _has_valid_token(self) -> bool:
        return self._access_token is not None and self._clock() < self._refresh_at

    def _sign(self, request: httpx.Request, token: str | None) -> None:
        request.headers["Authorization"] = f"Bearer {token}"
        request.headers[MEDIA_ID_HEADER] = self._settings.media_id

    def _fetch_token(self) -> Generator[httpx.Request, httpx.Response, None]:
        if self._refresh_token:
            response = yield self._token_request(
                {"grant_type": "refresh_token", "refresh_token": self._refresh_token}
            )
            if response.is_success:
                self._store(response)
                return
            logger.info(
                "Omerlo refresh token rejected (HTTP %s); using client credentials",
                response.status_code,
            )
            self._refresh_token = None

        response = yield self._token_request({"grant_type": "client_credentials"})
        if not response.is_success:
            raise OmerloAuthError(f"Omerlo token request failed with HTTP {response.status_code}")
        self._store(response)

    def _token_request(self, grant: dict[str, str]) -> httpx.Request:
        data = {
            **grant,
            "client_id": self._settings.client_id,
            "client_secret": self._settings.client_secret.get_secret_value(),
        }
        return httpx.Request("POST", str(self._settings.token_url), data=data)

    def _store(self, response: httpx.Response) -> None:
        try:
            payload = response.json()
            access_token = payload["access_token"]
        except (ValueError, KeyError):
            raise OmerloAuthError("Omerlo token response has no access_token") from None

        expires_in = payload.get("expires_in")
        if expires_in is None:
            # Without an expiry, keep the token until the API rejects it with a 401.
            self._refresh_at = math.inf
        else:
            try:
                lifetime = float(expires_in)
            except (TypeError, ValueError):
                raise OmerloAuthError("Omerlo token response has an invalid expires_in") from None
            # A margin longer than the lifetime would refetch on every request.
            margin = min(self._settings.token_refresh_margin_seconds, lifetime / 2)
            self._refresh_at = self._clock() + lifetime - margin
        self._access_token = access_token
        self._refresh_token = payload.get("refresh_token") or self._refresh_token
        logger.info("Obtained a new Omerlo access token (expires in %s s)", expires_in)


def create_omerlo_client(settings: OmerloSettings, **kwargs) -> httpx.Client:
    """An httpx client for the Reader API: base URL, timeout and authentication set."""
    return httpx.Client(
        base_url=str(settings.base_url),
        auth=OmerloAuth(settings),
        timeout=settings.timeout_seconds,
        **kwargs,
    )
