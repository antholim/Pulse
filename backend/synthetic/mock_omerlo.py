"""A mock of the Omerlo backoffice API that serves synthetic fixtures.

It behaves like the backoffice API where PULSE's connector depends on it (wiki
page "Omerlo API"): an `x-api-key` header (or `api_key` query parameter) that
identifies the tenant, community lists scoped by workspace that return summaries
and sort with `sort_by`, detail endpoints with the full record, metadata served
apart from the record, `{"data", "meta"}` responses with `meta.next` to follow,
and `{"error": message}` bodies on errors.

How the real API paginates is undocumented (#23). The mock answers `meta.next`
with an opaque cursor that is sent back as `after`, and takes `limit` everywhere.

    uv run python -m synthetic.mock_omerlo                       # seed 490, port 8100
    uv run python -m synthetic.mock_omerlo --fixtures synthetic/out
"""

import argparse
import base64
import binascii
import json
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from synthetic.fixture_loader import generate_fixtures, load_fixtures
from synthetic.omerlo_fixtures import DEFAULT_SEED, TenantData
from synthetic.omerlo_schema import summarize

API = "/api"
WORKSPACES = f"{API}/composer/v2/workspaces"
CATEGORIES = f"{API}/core/v2/categories"
COMMUNITY = f"{API}/community/v2"
# Community kinds as they appear in paths; fixture files use the same names.
COMMUNITY_KINDS = ("organizations", "people", "projects", "events")
SORT_FIELDS = ("name", "inserted_at", "updated_at")
SORT_VALUES = tuple(f"{f}-{d}" for f in SORT_FIELDS for d in ("asc", "desc"))
DEFAULT_SORT = "inserted_at-asc"
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def api_key_for(slug: str) -> str:
    """The mock's API key for a tenant, e.g. `mock-demo-capitale`."""
    return f"mock-{slug}"


def check_uuid(value: str) -> None:
    try:
        uuid.UUID(value)
    except ValueError:
        raise HTTPException(400, "Invalid uuid sent") from None


def sort_value(record: dict[str, Any], field: str) -> str:
    if field != "name":
        return record[field]
    if "name" in record:
        return record["name"]
    if "last_name" in record:
        return f"{record['last_name']} {record['first_name']}"
    return record["locales"][0]["name"] if record.get("locales") else ""


def encode_cursor(sort_by: str, record_id: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([sort_by, record_id]).encode()).decode()


def decode_cursor(cursor: str, sort_by: str) -> str:
    """The id of the record the cursor points at."""
    try:
        value = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except (binascii.Error, ValueError):
        raise HTTPException(400, "Invalid cursor") from None
    if not (isinstance(value, list) and len(value) == 2 and value[0] == sort_by):
        raise HTTPException(400, "Invalid cursor")
    return value[1]


def paginate(
    records: list[dict[str, Any]],
    *,
    sort_by: str,
    before: str | None,
    after: str | None,
    limit: int,
    base: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """One page of `records` in `sort_by` order (ties broken by id).

    `meta.next` passed as `after` gives the following page; `meta.previous` passed
    as `before` gives the preceding one.
    """
    if before and after:
        raise HTTPException(400, "Use either before or after, not both")
    field, direction = sort_by.rsplit("-", 1)
    ordered = sorted(records, key=lambda r: (sort_value(r, field), r["id"]))
    if direction == "desc":
        ordered.reverse()
    position = {r["id"]: i for i, r in enumerate(ordered)}

    def index_of(cursor: str) -> int:
        record_id = decode_cursor(cursor, sort_by)
        if record_id not in position:
            raise HTTPException(400, "Invalid cursor")
        return position[record_id]

    if after:
        start = index_of(after) + 1
        stop = min(start + limit, len(ordered))
    elif before:
        stop = index_of(before)
        start = max(0, stop - limit)
    else:
        start, stop = 0, min(limit, len(ordered))
    window = ordered[start:stop]
    meta = {
        "base": base,
        "next": encode_cursor(sort_by, window[-1]["id"])
        if window and stop < len(ordered)
        else None,
        "previous": encode_cursor(sort_by, window[0]["id"]) if window and start > 0 else None,
    }
    return window, meta


Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]


def create_app(tenants: list[TenantData], fixtures: Path | None = None) -> FastAPI:
    """The mock over `tenants`; with `fixtures`, it reloads them when the manifest changes."""
    by_key = {api_key_for(t.tenant.slug): t for t in tenants}
    app = FastAPI(title="Mock Omerlo backoffice API", description="Serves synthetic data only.")
    app.state.api_keys = {key: t.tenant.slug for key, t in by_key.items()}
    manifest = fixtures / "manifest.json" if fixtures else None
    loaded = {"manifest": manifest.read_text(encoding="utf-8") if manifest else None}

    def reload_if_changed() -> None:
        # The mutation script and its reset write the manifest last.
        if manifest is None:
            return
        text = manifest.read_text(encoding="utf-8")
        if text != loaded["manifest"]:
            by_key.clear()
            by_key.update({api_key_for(t.tenant.slug): t for t in load_fixtures(fixtures)})
            loaded["manifest"] = text

    @app.exception_handler(StarletteHTTPException)
    def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = ", ".join(".".join(map(str, e["loc"][1:])) for e in exc.errors())
        return JSONResponse({"error": f"Invalid parameters: {fields}"}, status_code=400)

    def current_tenant(request: Request) -> TenantData:
        reload_if_changed()
        key = request.headers.get("x-api-key") or request.query_params.get("api_key")
        if not key or key not in by_key:
            raise HTTPException(401, "Unauthorized access")
        return by_key[key]

    Tenant = Annotated[TenantData, Depends(current_tenant)]

    def find(tenant: TenantData, kind: str, record_id: str) -> dict[str, Any]:
        check_uuid(record_id)
        for record in tenant.resources[kind]:
            if record["id"] == record_id:
                return record
        raise HTTPException(404, "entity not found")

    # ------------------------------------------------------- composer, core

    @app.get(WORKSPACES)
    def list_workspaces(
        tenant: Tenant,
        before: str | None = None,
        after: str | None = None,
        limit: Limit = DEFAULT_LIMIT,
    ):
        records = tenant.resources["workspaces"]
        window, meta = paginate(
            records, sort_by=DEFAULT_SORT, before=before, after=after, limit=limit, base=WORKSPACES
        )
        return {"data": [summarize("workspaces", w) for w in window], "meta": meta}

    @app.get(f"{WORKSPACES}/{{workspace_id}}")
    def get_workspace(workspace_id: str, tenant: Tenant):
        return {"data": find(tenant, "workspaces", workspace_id)}

    @app.get(CATEGORIES)
    def list_categories(
        tenant: Tenant,
        before: str | None = None,
        after: str | None = None,
        limit: Limit = DEFAULT_LIMIT,
    ):
        records = tenant.resources["categories"]
        window, meta = paginate(
            records, sort_by=DEFAULT_SORT, before=before, after=after, limit=limit, base=CATEGORIES
        )
        return {"data": window, "meta": meta}

    @app.get(f"{CATEGORIES}/{{category_id}}")
    def get_category(category_id: str, tenant: Tenant):
        return {"data": find(tenant, "categories", category_id)}

    # ------------------------------------------------------------ community

    def community_routes(kind: str) -> None:
        list_path = f"{COMMUNITY}/workspaces/{{workspace_id}}/{kind}"
        detail_path = f"{COMMUNITY}/{kind}/{{record_id}}"

        def list_records(
            workspace_id: str,
            tenant: Tenant,
            sort_by: Annotated[str, Query(pattern="|".join(SORT_VALUES))] = DEFAULT_SORT,
            profile_type_ids: Annotated[list[str] | None, Query(alias="profile_type_ids[]")] = None,
            before: str | None = None,
            after: str | None = None,
            limit: Limit = DEFAULT_LIMIT,
        ):
            find(tenant, "workspaces", workspace_id)
            records = [
                r
                for r in tenant.resources[kind]
                if r["profile"]["workspace_id"] == workspace_id
                and (not profile_type_ids or r["profile"]["profile_type_id"] in profile_type_ids)
            ]
            base = list_path.format(workspace_id=workspace_id)
            window, meta = paginate(
                records, sort_by=sort_by, before=before, after=after, limit=limit, base=base
            )
            return {"data": [summarize(kind, r) for r in window], "meta": meta}

        def get_record(record_id: str, tenant: Tenant):
            return {"data": find(tenant, kind, record_id)}

        def get_metadata(record_id: str, tenant: Tenant):
            find(tenant, kind, record_id)
            return {"data": tenant.metadata.get(record_id, [])}

        app.get(list_path, name=f"list_{kind}")(list_records)
        app.get(detail_path, name=f"get_{kind}")(get_record)
        app.get(f"{detail_path}/metadata", name=f"get_{kind}_metadata")(get_metadata)

    for kind in COMMUNITY_KINDS:
        community_routes(kind)

    @app.get(f"{COMMUNITY}/events/{{event_id}}/sessions")
    def event_sessions(event_id: str, tenant: Tenant):
        find(tenant, "events", event_id)
        sessions = [s for s in tenant.resources["event_sessions"] if s["event_id"] == event_id]
        return {"data": sessions}

    return app


def build_app(argv: list[str] | None = None) -> tuple[FastAPI, argparse.Namespace]:
    parser = argparse.ArgumentParser(description="Mock Omerlo backoffice API (synthetic data)")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--seed", type=int, default=DEFAULT_SEED, help="generate in memory")
    source.add_argument("--fixtures", type=Path, help="serve files written by the generator")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args(argv)

    if args.fixtures:
        return create_app(load_fixtures(args.fixtures), args.fixtures), args
    return create_app(generate_fixtures(args.seed)), args


def main(argv: list[str] | None = None) -> None:
    import uvicorn

    app, args = build_app(argv)
    for key, slug in app.state.api_keys.items():
        print(f"Tenant {slug}: x-api-key {key}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
