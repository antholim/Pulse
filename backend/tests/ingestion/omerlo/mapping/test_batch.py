import logging

import pytest

from app.ingestion.connector import RawRecord
from app.ingestion.omerlo.mapping import batch
from app.ingestion.omerlo.mapping.batch import MappingFailure, map_records
from synthetic.fixture_loader import generate_fixtures
from synthetic.omerlo_fixtures import Sizes
from tests.ingestion.omerlo.mapping import payloads
from tests.ingestion.omerlo.mapping.payloads import profiles_block

SMALL = Sizes(organizations=30, people=40, events=6, projects=4, journalists=5)
# Fixture file name -> entity kind.
FIXTURE_KINDS = {
    "organizations": "organization",
    "people": "person",
    "projects": "project",
    "events": "event",
}


def raw(kind, payload, external_id=None, parent=None):
    return RawRecord(
        entity_kind=kind,
        external_id=external_id or payload.get("id", "?"),
        updated_at=None,
        payload=payload,
        parent_external_id=parent,
    )


def metadata(parent, *pairs, kind="organization"):
    entries = [{"key": key, "value": value} for key, value in pairs]
    return raw(f"{kind}_metadata", {"data": entries}, parent, parent)


def test_metadata_and_blocks_are_attached_to_their_parent():
    records = [
        raw("organization", payloads.organization()),
        metadata("org-1", ("crm_id", "C-1")),
        metadata("org-1", ("crm_id", "P-1"), kind="person"),
        raw("content", payloads.content()),
        raw(
            "content_blocks",
            {"data": [profiles_block("organization", "org-1")]},
            "content-1",
            "content-1",
        ),
    ]

    result = map_records(records)

    organization, content = result.records
    assert organization.external_ids == {"crm_id": ["C-1"]}
    assert content.attributes["linked_profiles"] == {"organization": ["org-1"]}
    assert result.failures == ()


def test_companions_of_one_parent_are_joined():
    records = [
        raw("organization", payloads.organization()),
        metadata("org-1", ("crm_id", "C-1")),
        metadata("org-1", ("neq", "123")),
    ]

    result = map_records(records)

    assert result.records[0].external_ids == {"crm_id": ["C-1"], "neq": ["123"]}


@pytest.mark.parametrize("parent", ["org-404", None])
def test_companions_without_their_parent_are_logged_and_dropped(parent, caplog):
    records = [raw("organization", payloads.organization()), metadata(parent, ("crm_id", "C-1"))]

    with caplog.at_level(logging.WARNING):
        result = map_records(records)

    assert result.records[0].external_ids == {}
    assert f"parent {parent} is not in this batch" in caplog.text


def test_reference_kinds_are_skipped():
    records = [
        raw("workspace", {"id": "ws-1"}),
        raw("category", {"id": "cat-1"}),
        raw("event_session", {"id": "session-1"}, parent="event-1"),
    ]

    result = map_records(records)

    assert result.records == ()


def test_malformed_companion_bodies_read_as_empty():
    records = [
        raw("organization", payloads.organization()),
        raw("organization_metadata", {"data": "oops"}, "org-1", "org-1"),
    ]

    result = map_records(records)

    assert result.records[0].external_ids == {}


def test_failures_are_logged_and_counted_without_stopping(caplog):
    nameless = payloads.organization() | {"id": "org-2", "name": None}
    records = [raw("organization", nameless), raw("project", payloads.project())]

    with caplog.at_level(logging.WARNING):
        result = map_records(records)

    assert [record.external_id for record in result.records] == ["project-1"]
    assert result.failures == (MappingFailure("organization", "org-2", "organization has no name"),)
    assert "organization org-2" in caplog.text


def test_unexpected_errors_are_counted_with_a_traceback(monkeypatch, caplog):
    def broken(*args, **kwargs):
        raise KeyError("surprise")

    monkeypatch.setattr(batch, "map_record", broken)

    with caplog.at_level(logging.ERROR):
        result = map_records([raw("project", payloads.project())])

    assert result.failures == (MappingFailure("project", "project-1", "unexpected KeyError"),)
    assert caplog.records[0].exc_info is not None


@pytest.fixture(scope="module")
def synthetic_tenant():
    return generate_fixtures(seed=11, sizes=SMALL)[0]


def test_every_synthetic_record_maps(synthetic_tenant):
    kinds = {
        payload["id"]: kind
        for file_name, kind in FIXTURE_KINDS.items()
        for payload in synthetic_tenant.resources[file_name]
    }
    records = [
        raw(kind, payload)
        for file_name, kind in FIXTURE_KINDS.items()
        for payload in synthetic_tenant.resources[file_name]
    ]
    records += [
        raw(f"{kinds[record_id]}_metadata", {"data": entries}, record_id, record_id)
        for record_id, entries in synthetic_tenant.metadata.items()
    ]

    result = map_records(records)

    assert result.failures == ()
    assert len(result.records) == len(kinds)
    organizations = [r for r in result.records if r.kind == "organization"]
    assert all(r.name_normalized for r in organizations)
    assert any(r.external_ids.get("crm_id") for r in organizations)
    assert all(r.workspace_id for r in result.records)
    with_website = [r for r in organizations if r.attributes["identifiers"]["domains"]]
    assert with_website
    assert all(r.domain == r.attributes["identifiers"]["domains"][0] for r in with_website)
