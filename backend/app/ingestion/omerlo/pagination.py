"""Pagination for the Omerlo backoffice API.

List endpoints answer with `{"data": [...], "meta": {"base", "next", "previous"}}`,
and `meta.next` is null on the last page. What `next` holds is not documented
(#23): an absolute URL is followed as is, anything else is sent back as the
`after` cursor, the parameter the workspaces and categories lists document.
"""

from collections.abc import Iterator
from typing import Any

import httpx

from app.ingestion.omerlo.client import OmerloAPIError, get_json

DEFAULT_PAGE_SIZE = 100


def paginate(
    client: httpx.Client,
    path: str,
    *,
    page_size: int | None = None,
    params: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield every item of a list endpoint, following `meta.next` until the last page.

    `page_size` is sent as `limit`; leave it out for endpoints that do not document it.
    """
    base = {**(params or {})}
    if page_size is not None:
        base["limit"] = page_size
    url, query = path, base
    seen: set[str] = set()
    while True:
        body = get_json(client, url, query)
        items = body.get("data")
        if not isinstance(items, list):
            raise OmerloAPIError(f"{path}: response has no data list")
        yield from items

        next_page = (body.get("meta") or {}).get("next")
        if not next_page or not items:
            return
        if next_page in seen:
            raise OmerloAPIError(f"{path}: next page {next_page!r} returned twice")
        seen.add(next_page)
        if next_page.startswith(("http://", "https://")):
            # The API key goes with the request, so only follow links to the same API.
            if httpx.URL(next_page).host != client.base_url.host:
                raise OmerloAPIError(f"{path}: next page points to another host")
            url, query = next_page, None
        else:
            url, query = path, {**base, "after": next_page}
