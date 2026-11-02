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
    # Arrange
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

    # Act
    result = map_records(records)

    # Assert
    organization, content = result.records
    assert organization.external_ids == {"crm_id": ["C-1"]}
    assert content.attributes["linked_profiles"] == {"organization": ["org-1"]}
    assert result.failures == ()


def test_companions_of_one_parent_are_joined():
    # Arrange
    records = [
        raw("organization", payloads.organization()),
        metadata("org-1", ("crm_id", "C-1")),
        metadata("org-1", ("neq", "123")),
    ]

    # Act
    result = map_records(records)

    # Assert
    assert result.records[0].external_ids == {"crm_id": ["C-1"], "neq": ["123"]}


@pytest.mark.parametrize("parent", ["org-404", None])
def test_companions_without_their_parent_are_logged_and_dropped(parent, caplog):
    # Arrange
    records = [raw("organization", payloads.organization()), metadata(parent, ("crm_id", "C-1"))]

    # Act
    with caplog.at_level(logging.WARNING):
        result = map_records(records)

    # Assert
    assert result.records[0].external_ids == {}
    assert f"parent {parent} is not in this batch" in caplog.text


def test_reference_kinds_are_skipped():
    # Arrange
    records = [
        raw("workspace", {"id": "ws-1"}),
        raw("category", {"id": "cat-1"}),
        raw("event_session", {"id": "session-1"}, parent="event-1"),
    ]

    # Act
    result = map_records(records)

    # Assert
    assert result.records == ()


def test_malformed_companion_bodies_read_as_empty():
    # Arrange
    records = [
        raw("organization", payloads.organization()),
        raw("organization_metadata", {"data": "oops"}, "org-1", "org-1"),
    ]

    # Act
    result = map_records(records)

    # Assert
    assert result.records[0].external_ids == {}


def test_failures_are_logged_and_counted_without_stopping(caplog):
    # Arrange
    nameless = payloads.organization() | {"id": "org-2", "name": None}
    records = [raw("organization", nameless), raw("project", payloads.project())]

    # Act
    with caplog.at_level(logging.WARNING):
        result = map_records(records)

    # Assert
    assert [record.external_id for record in result.records] == ["project-1"]
    assert result.failures == (MappingFailure("organization", "org-2", "organization has no name"),)
    assert "organization org-2" in caplog.text


def test_unexpected_errors_are_counted_with_a_traceback(monkeypatch, caplog):
    # Arrange
    def broken(*args, **kwargs):
        raise KeyError("surprise")

    monkeypatch.setattr(batch, "map_record", broken)

    # Act
    with caplog.at_level(logging.ERROR):
        result = map_records([raw("project", payloads.project())])

    # Assert
    assert result.failures == (MappingFailure("project", "project-1", "unexpected KeyError"),)
    assert caplog.records[0].exc_info is not None


@pytest.fixture(scope="module")
def synthetic_tenant():
    return generate_fixtures(seed=11, sizes=SMALL)[0]


def test_every_synthetic_record_maps(synthetic_tenant):
    # Arrange
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

    # Act
    result = map_records(records)

    # Assert
    assert result.failures == ()
    assert len(result.records) == len(kinds)
    organizations = [r for r in result.records if r.kind == "organization"]
    assert all(r.name_normalized for r in organizations)
    assert any(r.external_ids.get("crm_id") for r in organizations)
    assert all(r.workspace_id for r in result.records)
    with_website = [r for r in organizations if r.attributes["identifiers"]["domains"]]
    assert with_website
    assert all(r.domain == r.attributes["identifiers"]["domains"][0] for r in with_website)


@pytest.mark.parametrize("kind", ["organization", "person", "event", "project", "content"])
def test_cleaning_runs_for_each_kind_and_deduplicates_only_exact_batch_repeats(kind):
    builder = getattr(payloads, kind)
    payload = builder()
    # This nested field is retained by all five mappers.
    if kind == "person":
        payload["first_name"] = "  Marie   Ève  "
    else:
        payload["quality_note"] = "  QuÃ©bec   test  "
    other_id = payload | {"id": "another-id"}
    changed = payload | ({"last_name": "Changed"} if kind == "person" else {"revision": 2})
    records = [raw(kind, p) for p in (payload, payload, other_id, changed)]

    result = map_records(records)

    assert result.failures == ()
    assert len(result.records) == 3
    assert result.cleaning_flag_counts == {"duplicate in current batch": 1}
    assert result.records[1].external_id == "another-id"
    expected = batch.map_record(kind, payload)
    assert result.records[0].attributes == expected.attributes
    assert result.records[0].external_ids == expected.external_ids
    # A fresh batch must not remember the first one's ids.
    assert len(map_records([raw(kind, payload)]).records) == 1


def test_removing_repeats_preserves_the_last_payload_for_versioning():
    original = payloads.organization()
    changed = original | {"name": "Changed"}
    result = map_records([raw("organization", p) for p in (original, changed, original)])
    assert len(result.records) == 2
    assert result.records[-1].attributes["name"] == original["name"]


@pytest.mark.parametrize("kind", ["organization", "person", "event", "project", "content"])
def test_cleaning_preserves_nested_text_and_external_identifiers(kind):
    # Arrange
    markers = ["n/a", "na", "none", "null", "unknown", "-"]
    payload = getattr(payloads, kind)()
    if kind == "person":
        payload["first_name"] = "Unknown"
    else:
        payload |= {
            "description": "First paragraph.\n\nSecond paragraph.",
            "markers": markers,
            "encoding_literal": "QuÃ©bec",
        }
    pairs = [{"key": "crm_id", "value": "NA"}]
    expected = batch.map_record(kind, payload, metadata=pairs)

    # Act
    result = map_records(
        [
            raw(kind, payload),
            metadata(payload["id"], ("crm_id", "NA"), kind=kind),
        ]
    )

    # Assert
    assert result.failures == ()
    (record,) = result.records
    assert record.attributes == expected.attributes
    assert record.external_ids == {"crm_id": ["NA"]}
    if kind == "person":
        assert record.attributes["first_name"] == "Unknown"
    else:
        assert record.attributes["description"] == "First paragraph.\n\nSecond paragraph."
        assert record.attributes["markers"] == markers
        assert record.attributes["encoding_literal"] == "QuÃ©bec"


def test_nested_attribute_changes_are_not_removed_as_duplicates():
    # Arrange
    original = payloads.organization() | {"description": "First\nSecond"}
    changed = original | {"description": "First Second"}

    # Act
    result = map_records([raw("organization", p) for p in (original, changed)])

    # Assert
    assert result.failures == ()
    assert len(result.records) == 2
    assert result.records[0].attributes["description"] == "First\nSecond"
    assert result.records[1].attributes["description"] == "First Second"
    assert result.cleaning_flag_counts.get("duplicate in current batch", 0) == 0


@pytest.mark.parametrize("external_id", ["na", "none", "null", "unknown", "-", "N/A"])
def test_cleaning_missing_required_id_is_a_mapping_failure(external_id, caplog):
    # Arrange
    invalid = payloads.organization() | {"id": external_id}
    valid = payloads.organization() | {"id": "valid-org"}

    # Act
    with caplog.at_level(logging.WARNING):
        result = map_records([raw("organization", invalid), raw("organization", valid)])

    # Assert
    assert [r.external_id for r in result.records] == ["valid-org"]
    assert result.failures == (
        MappingFailure(
            "organization", external_id, "cleaning removed required fields: external_id"
        ),
    )
    assert result.cleaning_flag_counts == {"required field is missing": 1}
    assert external_id in caplog.text


def test_cleaning_missing_required_name_is_a_mapping_failure():
    # Arrange
    payload = payloads.organization() | {"name": "Unknown"}

    # Act
    result = map_records([raw("organization", payload)])

    # Assert
    assert result.records == ()
    assert result.failures == (
        MappingFailure(
            "organization", "org-1", "cleaning removed required fields: name_normalized"
        ),
    )
    assert result.cleaning_flag_counts == {"required field is missing": 1}


def test_cleaning_allows_optional_workspace_and_project_name():
    # Arrange
    payload = payloads.project() | {"profile": None, "locales": None}

    # Act
    result = map_records([raw("project", payload)])

    # Assert
    assert result.failures == ()
    (record,) = result.records
    assert record.workspace_id is None
    assert record.name_normalized is None
