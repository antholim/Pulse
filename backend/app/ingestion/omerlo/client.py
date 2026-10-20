"""HTTP access to the Omerlo backoffice API (ADR D8, wiki page "Omerlo API").

Every request carries the API key in the `x-api-key` header. The documented
`api_key` query parameter is never used, because URLs end up in logs.

Errors come back as `{"error": message}`. `get_json` turns them into exceptions
the sync run can act on: a rejected key or a missing role stops the run (retrying
cannot help), a missing record is skipped, and other HTTP errors are raised as
`httpx.HTTPStatusError` for the sync run to retry.
"""

from typing import Any

import httpx

from app.ingestion.omerlo.settings import OmerloSettings

API_KEY_HEADER = "x-api-key"


class OmerloAPIError(Exception):
    """The backoffice API returned a response PULSE cannot use."""


class OmerloAuthError(OmerloAPIError):
    """The API key was rejected (401) or lacks the role for a resource (403)."""


class OmerloNotFoundError(OmerloAPIError):
    """The record does not exist, for example because it was deleted mid-sync."""


def create_omerlo_client(settings: OmerloSettings, **kwargs: Any) -> httpx.Client:
    """An httpx client for the backoffice API: base URL, API key and timeout set."""
    return httpx.Client(
        base_url=str(settings.base_url),
        headers={API_KEY_HEADER: settings.api_key.get_secret_value()},
        timeout=settings.timeout_seconds,
        **kwargs,
    )


def get_json(
    client: httpx.Client, path: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    response = client.get(path, params=params)
    if response.status_code == httpx.codes.UNAUTHORIZED:
        raise OmerloAuthError(f"{path}: Omerlo rejected the API key (HTTP 401)")
    if response.status_code == httpx.codes.FORBIDDEN:
        raise OmerloAuthError(f"{path}: the API key lacks the role for this resource (HTTP 403)")
    if response.status_code == httpx.codes.NOT_FOUND:
        raise OmerloNotFoundError(f"{path}: {error_message(response)}")
    response.raise_for_status()
    return read_json(response, path)


def read_json(response: httpx.Response, path: str) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        raise OmerloAPIError(f"{path}: response is not JSON") from None
    if not isinstance(body, dict):
        raise OmerloAPIError(f"{path}: response is not a JSON object")
    return body


def error_message(response: httpx.Response) -> str:
    try:
        return str(response.json()["error"])
    except (ValueError, KeyError, TypeError):
        return f"HTTP {response.status_code}"
