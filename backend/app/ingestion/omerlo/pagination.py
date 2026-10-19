"""Cursor pagination for the Omerlo Reader API.

List endpoints take `before`, `after` and `limit`, and answer with
`{"data": [...], "assocs": {...}, "meta": {"base", "next", "previous"}}`.
`meta.next` is passed back as `after` to get the following page (to verify on
staging in #23).
"""

from collections.abc import Iterator
from typing import Any

import httpx

DEFAULT_PAGE_SIZE = 100


class OmerloAPIError(Exception):
    """The Reader API returned a response PULSE cannot use."""


def paginate(
    client: httpx.Client,
    path: str,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    params: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield every item of a list endpoint, following `meta.next` until the last page.

    HTTP errors are raised as `httpx.HTTPStatusError`; retrying is the sync run's job.
    """
    query = {**(params or {}), "limit": page_size}
    seen_cursors: set[str] = set()
    while True:
        response = client.get(path, params=query)
        response.raise_for_status()
        body = read_json(response, path)
        items = body.get("data")
        if not isinstance(items, list):
            raise OmerloAPIError(f"{path}: response has no data list")
        yield from items

        cursor = (body.get("meta") or {}).get("next")
        if not cursor or not items:
            return
        if cursor in seen_cursors:
            raise OmerloAPIError(f"{path}: cursor {cursor!r} returned twice")
        seen_cursors.add(cursor)
        query = {**(params or {}), "limit": page_size, "after": cursor}


def read_json(response: httpx.Response, path: str) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        raise OmerloAPIError(f"{path}: response is not JSON") from None
    if not isinstance(body, dict):
        raise OmerloAPIError(f"{path}: response is not a JSON object")
    return body
