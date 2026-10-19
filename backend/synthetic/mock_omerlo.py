"""A mock of the Omerlo Reader API that serves synthetic fixtures.

It behaves like the Reader API where PULSE's connector depends on it: an OAuth 2
client credentials token endpoint, `Authorization: Bearer` and
`x-omerlo-media-id` on every request, data scoped to the media id, cursor
pagination (`before`, `after`, `limit`) ordered by `updated_at`, and
`{"data", "assocs", "meta"}` responses. Paths mirror the ones the connector
assumes until staging confirms them (#23).
"""

import base64
import binascii
import json
import secrets
import time
from bisect import bisect_left, bisect_right
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from synthetic.omerlo_fixtures import TenantData

TOKEN_PATH = "/oauth/token"
API = "/api/media/v1"
LIST_PATHS = {
    "categories": f"{API}/categories",
    "profile_types": f"{API}/profile_types",
    "organizations": f"{API}/community/organizations",
    "people": f"{API}/community/people",
    "projects": f"{API}/community/projects",
    "events": f"{API}/community/events",
    "contents": f"{API}/contents",
}
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


@dataclass(frozen=True)
class MockSettings:
    client_id: str = "mock-client"
    client_secret: str = "mock-secret"
    token_ttl_seconds: int = 3600


SortKey = tuple[str, str]


def sort_key(item: dict[str, Any]) -> SortKey:
    # Categories and profile types have no updated_at; they sort by id.
    return (item.get("updated_at") or "", item["id"])


def encode_cursor(key: SortKey) -> str:
    return base64.urlsafe_b64encode(json.dumps(list(key)).encode()).decode()


def decode_cursor(cursor: str) -> SortKey:
    try:
        key = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except (binascii.Error, ValueError):
        raise HTTPException(400, "Invalid cursor") from None
    if not (isinstance(key, list) and len(key) == 2 and all(isinstance(k, str) for k in key)):
        raise HTTPException(400, "Invalid cursor")
    return key[0], key[1]


def paginate(
    items: list[dict[str, Any]], before: str | None, after: str | None, limit: int, base: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """One page of `items` ordered by `updated_at`.

    `meta.next` passed as `after` gives the following page; `meta.previous` passed
    as `before` gives the preceding one.
    """
    if before and after:
        raise HTTPException(400, "Use either before or after, not both")
    ordered = sorted(items, key=sort_key)
    keys = [sort_key(i) for i in ordered]
    if after:
        start = bisect_right(keys, decode_cursor(after))
        stop = min(start + limit, len(ordered))
    elif before:
        stop = bisect_left(keys, decode_cursor(before))
        start = max(0, stop - limit)
    else:
        start, stop = 0, min(limit, len(ordered))
    window = ordered[start:stop]
    meta = {
        "base": base,
        "next": encode_cursor(keys[stop - 1]) if window and stop < len(ordered) else None,
        "previous": encode_cursor(keys[start]) if window and start > 0 else None,
    }
    return window, meta


def create_app(
    tenants: list[TenantData],
    settings: MockSettings | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> FastAPI:
    settings = settings or MockSettings()
    by_media_id = {t.tenant.media_id: t for t in tenants}
    tokens: dict[str, float] = {}
    app = FastAPI(title="Mock Omerlo Reader API", description="Serves synthetic data only.")

    @app.post(TOKEN_PATH)
    def issue_token(
        grant_type: Annotated[str, Form()],
        client_id: Annotated[str | None, Form()] = None,
        client_secret: Annotated[str | None, Form()] = None,
    ):
        if grant_type != "client_credentials":
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
        valid = secrets.compare_digest(client_id or "", settings.client_id) and (
            secrets.compare_digest(client_secret or "", settings.client_secret)
        )
        if not valid:
            return JSONResponse({"error": "invalid_client"}, status_code=401)
        access_token = secrets.token_urlsafe(24)
        tokens[access_token] = clock() + settings.token_ttl_seconds
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": settings.token_ttl_seconds,
        }

    def current_tenant(request: Request) -> TenantData:
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or tokens.get(token, 0) <= clock():
            raise HTTPException(401, "Missing, invalid or expired bearer token")
        media_id = request.headers.get("x-omerlo-media-id")
        if not media_id:
            raise HTTPException(400, "The x-omerlo-media-id header is required")
        if media_id not in by_media_id:
            raise HTTPException(404, f"Unknown media {media_id!r}")
        return by_media_id[media_id]

    def list_route(kind: str, path: str):
        def list_items(
            tenant: Annotated[TenantData, Depends(current_tenant)],
            before: str | None = None,
            after: str | None = None,
            limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
        ):
            records = tenant.resources[kind]
            window, meta = paginate(records, before, after, limit, path)
            assocs: dict[str, Any] = {}
            if kind == "contents":
                # The list endpoint returns summaries; blocks come with the detail.
                window = [{k: v for k, v in c.items() if k != "blocks"} for c in window]
                wanted = {cid for c in window for cid in c["category_ids"]}
                categories = tenant.resources["categories"]
                assocs["categories"] = [c for c in categories if c["id"] in wanted]
            return {"data": window, "assocs": assocs, "meta": meta}

        app.get(path, name=f"list_{kind}")(list_items)

    for kind, path in LIST_PATHS.items():
        list_route(kind, path)

    return app
