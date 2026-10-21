"""Retry idempotent HTTP requests on network errors and server errors, with exponential backoff."""

import logging
import time
from collections.abc import Callable

import httpx

logger = logging.getLogger(__name__)

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class RetryTransport(httpx.BaseTransport):
    """Wraps a transport and retries a request until it gets a usable answer.

    Network errors, 429 and 5xx answers are retried; other answers, 401 and 403
    included, are returned at once. After the last attempt the error or the response
    goes to the caller as usual.
    """

    def __init__(
        self,
        transport: httpx.BaseTransport,
        *,
        attempts: int = 4,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if attempts < 1:
            raise ValueError("attempts must be at least 1")
        self._transport = transport
        self.attempts = attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self._sleep = sleep

    def delay(self, retry: int) -> float:
        """Seconds to wait before retry number `retry` (1 for the first retry)."""
        return min(self.base_delay * 2 ** (retry - 1), self.max_delay)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.method not in IDEMPOTENT_METHODS:
            return self._transport.handle_request(request)
        attempt = 1
        while True:
            try:
                response = self._transport.handle_request(request)
            except httpx.TransportError as error:
                if attempt >= self.attempts:
                    raise
                reason = type(error).__name__
            else:
                if attempt >= self.attempts or response.status_code not in RETRY_STATUSES:
                    return response
                response.close()
                reason = f"HTTP {response.status_code}"
            wait = self.delay(attempt)
            logger.warning(
                "Retrying %s %s in %.1fs (attempt %d of %d failed: %s)",
                request.method,
                request.url.path,
                wait,
                attempt,
                self.attempts,
                reason,
            )
            self._sleep(wait)
            attempt += 1

    def close(self) -> None:
        self._transport.close()
