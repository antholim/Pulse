import logging
from datetime import UTC, datetime

import httpx
import pytest
import respx

from app.ingestion.omerlo.client import OmerloAPIError, OmerloAuthError
from app.ingestion.omerlo.connector import (
    CATEGORIES,
    COMMUNITY,
    COMMUNITY_DETAIL,
    COMMUNITY_LIST,
    COMMUNITY_METADATA,
    EVENT_SESSIONS,
    WORKSPACE_DETAIL,
    WORKSPACES,
    OmerloConnector,
)

BASE_URL = "https://omerlo.test/api"
WATERMARK = datetime(2026, 10, 1, tzinfo=UTC)
OLD = "2026-09-01T00:00:00Z"
NEW = "2026-10-15T00:00:00Z"
NEWER = "2026-10-20T00:00:00Z"
WS = "ws-1"


def page(items, next_cursor=None):
    return httpx.Response(200, json={"data": items, "meta": {"next": next_cursor}})


def data(value):
    return httpx.Response(200, json={"data": value})


def url(template, **ids):
    return BASE_URL + template.format(**ids)


def list_url(kind, workspace_id=WS):
    return url(COMMUNITY_LIST, workspace_id=workspace_id, path=COMMUNITY[kind])


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL) as c:
        yield c


@pytest.fixture
def api():
    """Respx routes for one workspace and no records; tests add what they need."""
    with respx.mock(assert_all_called=False) as router:
        router.get(url(WORKSPACES)).mock(return_value=page([{"id": WS, "updated_at": OLD}]))
        router.get(url(WORKSPACE_DETAIL, id=WS)).mock(
            return_value=data({"id": WS, "updated_at": OLD, "statuses": []})
        )
        router.get(url(CATEGORIES)).mock(return_value=page([]))
        for kind in COMMUNITY:
            router.get(list_url(kind)).mock(return_value=page([]))
        yield router


def add_record(api, kind, record_id, updated_at=OLD, metadata=(), sessions=()):
    """Route the detail, metadata and (for events) sessions of one record."""
    path = COMMUNITY[kind]
    detail = {"id": record_id, "updated_at": updated_at, "contact": [{"locale": "fr"}]}
    routes = {
        "detail": api.get(url(COMMUNITY_DETAIL, path=path, id=record_id)).mock(
            return_value=data(detail)
        ),
        "metadata": api.get(url(COMMUNITY_METADATA, path=path, id=record_id)).mock(
            return_value=data(list(metadata))
        ),
    }
    if kind == "event":
        routes["sessions"] = api.get(url(EVENT_SESSIONS, id=record_id)).mock(
            return_value=data(list(sessions))
        )
    return {"id": record_id, "updated_at": updated_at}, routes


def kinds_and_ids(records):
    return [(r.entity_kind, r.external_id) for r in records]


def test_full_sync_yields_reference_data_then_each_record_with_its_extras(api, client):
    api.get(url(CATEGORIES)).mock(return_value=page([{"id": "c1", "updated_at": OLD}]))
    org, _ = add_record(api, "organization", "o1", metadata=[{"key": "crm_id", "value": "CRM-1"}])
    event, _ = add_record(api, "event", "e1", sessions=[{"id": "s1", "updated_at": OLD}])
    api.get(list_url("organization")).mock(return_value=page([org]))
    api.get(list_url("event")).mock(return_value=page([event]))

    records = list(OmerloConnector(client).fetch_since(None))

    assert kinds_and_ids(records) == [
        ("workspace", WS),
        ("category", "c1"),
        ("organization", "o1"),
        ("organization_metadata", "o1"),
        ("event", "e1"),
        ("event_metadata", "e1"),
        ("event_session", "s1"),
    ]
    workspace, _, organization, metadata, _, _, session = records
    assert workspace.payload["statuses"] == []
    assert organization.payload["contact"] == [{"locale": "fr"}]
    assert organization.updated_at == datetime(2026, 9, 1, tzinfo=UTC)
    assert metadata.payload == {"data": [{"key": "crm_id", "value": "CRM-1"}]}
    assert metadata.parent_external_id == "o1"
    assert session.parent_external_id == "e1"


def test_lists_are_read_newest_first_and_sized_only_where_documented(api, client):
    list(OmerloConnector(client, page_size=25).fetch_since(None))

    calls = {str(c.request.url.copy_with(query=None)): c.request.url.params for c in api.calls}
    assert dict(calls[url(WORKSPACES)]) == {"limit": "25"}
    assert dict(calls[url(CATEGORIES)]) == {"limit": "25"}
    assert dict(calls[list_url("event")]) == {"sort_by": "updated_at-desc", "limit": "25"}
    for kind in ("organization", "person", "project"):
        assert dict(calls[list_url(kind)]) == {"sort_by": "updated_at-desc"}


def test_incremental_sync_stops_at_the_first_record_older_than_the_watermark(api, client):
    newer, _ = add_record(api, "organization", "o-newer", NEWER)
    new, _ = add_record(api, "organization", "o-new", NEW)
    old, old_routes = add_record(api, "organization", "o-old", OLD)
    listing = api.get(list_url("organization")).mock(
        side_effect=[page([newer, new], "c2"), page([old], "c3"), page([], None)]
    )

    connector = OmerloConnector(client, entity_kinds=["organization"])
    records = list(connector.fetch_since(WATERMARK))

    assert kinds_and_ids(records) == [
        ("organization", "o-newer"),
        ("organization_metadata", "o-newer"),
        ("organization", "o-new"),
        ("organization_metadata", "o-new"),
    ]
    assert listing.call_count == 2  # the third page is never requested
    assert old_routes["detail"].call_count == 0
    assert old_routes["metadata"].call_count == 0


def test_watermark_is_inclusive(api, client):
    record, _ = add_record(api, "person", "p1", "2026-10-01T00:00:00Z")
    api.get(list_url("person")).mock(return_value=page([record]))

    connector = OmerloConnector(client, entity_kinds=["person"], metadata=False)

    assert kinds_and_ids(connector.fetch_since(WATERMARK)) == [("person", "p1")]


def test_unchanged_workspaces_and_categories_are_skipped(api, client):
    api.get(url(CATEGORIES)).mock(
        return_value=page([{"id": "old", "updated_at": OLD}, {"id": "new", "updated_at": NEW}])
    )

    records = list(OmerloConnector(client).fetch_since(WATERMARK))

    assert kinds_and_ids(records) == [("category", "new")]
    paths = [c.request.url.path for c in api.calls]
    assert "/api" + WORKSPACES in paths  # still read, to know which workspaces to list
    assert "/api" + WORKSPACE_DETAIL.format(id=WS) not in paths


def test_every_visible_workspace_is_synced_by_default(api, client):
    api.get(url(WORKSPACES)).mock(return_value=page([{"id": WS}, {"id": "ws-2"}]))
    api.get(list_url("project", "ws-2")).mock(return_value=page([]))

    list(OmerloConnector(client, entity_kinds=["project"]).fetch_since(None))

    listed = [str(c.request.url.copy_with(query=None)) for c in api.calls]
    assert list_url("project") in listed
    assert list_url("project", "ws-2") in listed


def test_workspace_ids_limit_the_sync(api, client):
    api.get(url(WORKSPACES)).mock(return_value=page([{"id": WS}, {"id": "ws-2"}]))
    second = api.get(list_url("project", "ws-2")).mock(return_value=page([]))

    connector = OmerloConnector(client, workspace_ids=[WS], entity_kinds=["project"])
    list(connector.fetch_since(None))

    assert second.call_count == 0


def test_configured_workspace_the_key_cannot_see_is_an_error(api, client):
    connector = OmerloConnector(client, workspace_ids=[WS, "ws-gone"])

    with pytest.raises(OmerloAPIError, match="ws-gone"):
        list(connector.fetch_since(None))


def test_record_deleted_before_its_detail_is_read_is_skipped(api, client, caplog):
    gone, routes = add_record(api, "organization", "o-gone")
    routes["detail"].mock(return_value=httpx.Response(404, json={"error": "entity not found"}))
    kept, _ = add_record(api, "organization", "o-kept")
    api.get(list_url("organization")).mock(return_value=page([gone, kept]))

    connector = OmerloConnector(client, entity_kinds=["organization"], metadata=False)
    records = list(connector.fetch_since(None))

    assert kinds_and_ids(records) == [("organization", "o-kept")]
    assert "disappeared" in caplog.text


@pytest.mark.parametrize("extra", ["metadata", "sessions"])
def test_record_deleted_before_its_extras_are_read_keeps_the_detail(api, client, extra):
    event, routes = add_record(api, "event", "e1")
    routes[extra].mock(return_value=httpx.Response(404, json={"error": "entity not found"}))
    api.get(list_url("event")).mock(return_value=page([event]))

    records = list(OmerloConnector(client, entity_kinds=["event"]).fetch_since(None))

    assert ("event", "e1") in kinds_and_ids(records)


def test_metadata_and_sessions_can_be_switched_off(api, client):
    event, routes = add_record(api, "event", "e1")
    api.get(list_url("event")).mock(return_value=page([event]))

    connector = OmerloConnector(
        client, entity_kinds=["event"], metadata=False, event_sessions=False
    )

    assert kinds_and_ids(connector.fetch_since(None)) == [("event", "e1")]
    assert routes["metadata"].call_count == 0
    assert routes["sessions"].call_count == 0


def test_detail_without_a_data_object_raises(api, client):
    record, routes = add_record(api, "person", "p1")
    routes["detail"].mock(return_value=httpx.Response(200, json={"data": None}))
    api.get(list_url("person")).mock(return_value=page([record]))

    with pytest.raises(OmerloAPIError, match="no data object"):
        list(OmerloConnector(client, entity_kinds=["person"]).fetch_since(None))


def test_rejected_api_key_stops_the_sync(api, client):
    api.get(url(WORKSPACES)).mock(
        return_value=httpx.Response(401, json={"error": "Unauthorized access"})
    )

    with pytest.raises(OmerloAuthError):
        list(OmerloConnector(client).fetch_since(None))


def test_items_without_an_id_are_skipped_and_logged(api, client, caplog):
    record, _ = add_record(api, "person", "p1")
    api.get(list_url("person")).mock(return_value=page([{"first_name": "Nameless"}, record]))

    with caplog.at_level(logging.WARNING):
        connector = OmerloConnector(client, entity_kinds=["person"], metadata=False)
        records = list(connector.fetch_since(None))

    assert kinds_and_ids(records) == [("person", "p1")]
    assert "without an id" in caplog.text
    assert "Nameless" not in caplog.text


def test_unknown_entity_kind_is_rejected(client):
    with pytest.raises(ValueError, match="subscriber"):
        OmerloConnector(client, entity_kinds=["organization", "subscriber"])
