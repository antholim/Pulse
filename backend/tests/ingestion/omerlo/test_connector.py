import logging
from datetime import UTC, datetime

import httpx
import pytest
import respx

from app.ingestion.omerlo.connector import (
    CONTENT_DETAIL,
    ENDPOINTS,
    EVENT_PARTICIPANTS,
    OmerloConnector,
)

BASE_URL = "https://omerlo.test"
WATERMARK = datetime(2026, 10, 1, tzinfo=UTC)
OLD = "2026-09-01T00:00:00Z"
NEW = "2026-10-15T00:00:00Z"


def page(items, next_cursor=None):
    return httpx.Response(200, json={"data": items, "assocs": {}, "meta": {"next": next_cursor}})


def url(path):
    return BASE_URL + path


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL) as c:
        yield c


def mock_empty_except(*kinds):
    for kind, path in ENDPOINTS.items():
        if kind not in kinds:
            respx.get(url(path)).mock(return_value=page([]))


@respx.mock
def test_full_sync_yields_every_kind_in_order_with_untouched_payloads(client):
    org = {"id": 7, "name": "Groupe Exemple ltée", "updated_at": OLD, "extra": {"x": 1}}
    respx.get(url(ENDPOINTS["category"])).mock(return_value=page([{"id": "c1", "name": "Culture"}]))
    respx.get(url(ENDPOINTS["organization"])).mock(return_value=page([org]))
    mock_empty_except("category", "organization")

    records = list(OmerloConnector(client).fetch_since(None))

    assert [(r.entity_kind, r.external_id) for r in records] == [
        ("category", "c1"),
        ("organization", "7"),
    ]
    assert records[1].payload == org
    assert records[1].updated_at == datetime(2026, 9, 1, tzinfo=UTC)


@respx.mock
def test_incremental_sync_keeps_changed_records_and_untimestamped_ones(client):
    respx.get(url(ENDPOINTS["category"])).mock(return_value=page([{"id": "c1"}]))
    respx.get(url(ENDPOINTS["organization"])).mock(
        return_value=page([{"id": "old", "updated_at": OLD}, {"id": "new", "updated_at": NEW}])
    )
    mock_empty_except("category", "organization")

    records = list(OmerloConnector(client).fetch_since(WATERMARK))

    assert [r.external_id for r in records] == ["c1", "new"]


@respx.mock
def test_content_detail_is_fetched_only_for_changed_contents(client):
    respx.get(url(ENDPOINTS["content"])).mock(
        return_value=page([{"id": "a", "updated_at": OLD}, {"id": "b", "updated_at": NEW}])
    )
    detail = {"id": "b", "updated_at": NEW, "blocks": [{"type": "profiles", "ids": ["7"]}]}
    detail_b = respx.get(url(CONTENT_DETAIL.format(id="b"))).mock(
        return_value=httpx.Response(200, json={"data": detail})
    )
    detail_a = respx.get(url(CONTENT_DETAIL.format(id="a")))

    records = list(OmerloConnector(client, entity_kinds=["content"]).fetch_since(WATERMARK))

    assert [r.payload for r in records] == [detail]
    assert detail_b.call_count == 1
    assert detail_a.call_count == 0


@respx.mock
def test_content_details_can_be_switched_off(client):
    summary = {"id": "b", "updated_at": NEW}
    respx.get(url(ENDPOINTS["content"])).mock(return_value=page([summary]))

    connector = OmerloConnector(client, entity_kinds=["content"], content_details=False)

    assert [r.payload for r in connector.fetch_since(None)] == [summary]


@respx.mock
def test_content_deleted_before_its_detail_is_skipped(client, caplog):
    respx.get(url(ENDPOINTS["content"])).mock(return_value=page([{"id": "gone"}]))
    respx.get(url(CONTENT_DETAIL.format(id="gone"))).mock(return_value=httpx.Response(404))

    records = list(OmerloConnector(client, entity_kinds=["content"]).fetch_since(None))

    assert records == []
    assert "disappeared" in caplog.text


@respx.mock
def test_event_participants_are_read_for_every_event(client):
    respx.get(url(ENDPOINTS["event"])).mock(
        return_value=page([{"id": "e1", "updated_at": OLD}, {"id": "e2", "updated_at": NEW}])
    )
    for event_id, people in (("e1", [{"id": "p1"}]), ("e2", [{"id": "p1"}, {"id": "p2"}])):
        respx.get(url(EVENT_PARTICIPANTS.format(id=event_id))).mock(return_value=page(people))

    records = list(OmerloConnector(client, entity_kinds=["event"]).fetch_since(WATERMARK))

    assert [(r.entity_kind, r.external_id, r.parent_external_id) for r in records] == [
        ("event_participant", "e1:p1", "e1"),
        ("event", "e2", None),
        ("event_participant", "e2:p1", "e2"),
        ("event_participant", "e2:p2", "e2"),
    ]


@respx.mock
def test_event_participants_can_be_switched_off(client):
    respx.get(url(ENDPOINTS["event"])).mock(return_value=page([{"id": "e1"}]))
    participants = respx.get(url(EVENT_PARTICIPANTS.format(id="e1")))

    connector = OmerloConnector(client, entity_kinds=["event"], event_participants=False)

    assert [r.entity_kind for r in connector.fetch_since(None)] == ["event"]
    assert participants.call_count == 0


@respx.mock
def test_items_without_an_id_are_skipped_and_logged(client, caplog):
    respx.get(url(ENDPOINTS["person"])).mock(
        return_value=page([{"first_name": "Nameless"}, {"id": "p1"}])
    )

    with caplog.at_level(logging.WARNING):
        records = list(OmerloConnector(client, entity_kinds=["person"]).fetch_since(None))

    assert [r.external_id for r in records] == ["p1"]
    assert "without an id" in caplog.text
    assert "Nameless" not in caplog.text


@respx.mock
def test_page_size_is_passed_to_every_list_call(client):
    route = respx.get(url(ENDPOINTS["organization"])).mock(return_value=page([]))

    list(OmerloConnector(client, page_size=25, entity_kinds=["organization"]).fetch_since(None))

    assert route.calls.last.request.url.params["limit"] == "25"


def test_unknown_entity_kind_is_rejected(client):
    with pytest.raises(ValueError, match="subscriber"):
        OmerloConnector(client, entity_kinds=["organization", "subscriber"])
