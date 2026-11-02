import pytest

from synthetic.omerlo_fixtures import OmerloFixtureGenerator
from tests.fixture_diff import (
    assert_fields_correspond,
    direct_change,
    expected,
    mapped_records,
    normalized_paths,
)
from tests.synthetic.conftest import SMALL


@pytest.mark.parametrize(
    ("kind", "path", "paths"),
    [
        ("organization", "name", {"attributes.name", "name_normalized"}),
        ("organization", "profile.canonical_url", {"attributes.profile.canonical_url"}),
        (
            "organization",
            "contact[fr].website",
            {"attributes.contact[fr].website", "attributes.identifiers.domains", "domain"},
        ),
        (
            "organization",
            "contact[en].phone",
            {"attributes.contact[en].phone", "attributes.identifiers.phones"},
        ),
        ("organization", "metadata.crm_id", {"external_ids.crm_id"}),
        ("person", "last_name", {"attributes.last_name", "name_normalized"}),
        ("person", "locales[en].job_title", {"attributes.job_titles.en"}),
        ("person", "contact[fr].email", {"attributes.identifiers.emails"}),
        ("person", "contact[fr].linkedin", {"attributes.identifiers.linkedin", "linkedin"}),
        ("person", "contact[fr].phone", set()),
    ],
)
def test_fixture_paths_translate_to_normalized_paths(kind, path, paths):
    # Act
    found = normalized_paths(kind, path)

    # Assert
    assert found == paths


@pytest.mark.parametrize(
    ("kind", "change", "entry"),
    [
        (
            "organization",
            {"field": "contact[fr].phone", "before": "1", "after": "2"},
            ("attributes.contact[fr].phone", "1", "2"),
        ),
        (
            "organization",
            {"field": "metadata.crm_id", "before": None, "after": "CRM-2"},
            ("external_ids.crm_id", None, ["CRM-2"]),
        ),
        (
            "person",
            {"field": "locales[fr].job_title", "before": "a", "after": "b"},
            ("attributes.job_titles.fr", "a", "b"),
        ),
        ("person", {"field": "contact[fr].email", "before": "a", "after": "b"}, None),
    ],
)
def test_a_direct_change_keeps_the_fixture_values(kind, change, entry):
    # Act
    found = direct_change(kind, change)

    # Assert
    assert found == entry


def test_only_kinds_stored_as_source_records_are_expected():
    # Arrange
    diff = {
        "added": [{"kind": "people", "id": "p-1"}, {"kind": "workspaces", "id": "w-1"}],
        "modified": [{"kind": "organizations", "id": "o-1", "changes": []}],
        "removed": [{"kind": "events", "id": "e-1"}, {"kind": "event_sessions", "id": "s-1"}],
    }

    # Act
    result = expected(diff)

    # Assert
    assert result.added == {("person", "p-1")}
    assert result.modified == {("organization", "o-1"): []}
    assert result.removed == {("event", "e-1")}


def test_mapped_records_can_be_limited_to_recent_updates():
    # Arrange
    [tenant, _] = OmerloFixtureGenerator(5, SMALL).generate()
    latest = max(r["updated_at"] for r in tenant.resources["organizations"])

    # Act
    everything = mapped_records(tenant)
    recent = mapped_records(tenant, updated_after=latest)

    # Assert
    kinds = {record.kind for record in everything}
    assert kinds == {"organization", "person", "project", "event"}
    assert len(recent) < len(everything)
    assert all(record.external_id for record in recent)


def test_fields_must_be_explained_by_a_fixture_change():
    # Arrange
    changes = [{"field": "name", "before": "A", "after": "B"}]
    fields = {
        "attributes.name": {"before": "A", "after": "B"},
        "name_normalized": {"before": "a", "after": "b"},
    }

    # Act
    assert_fields_correspond("organization", changes, fields)

    # Assert
    with pytest.raises(AssertionError, match="no fixture change explains"):
        assert_fields_correspond("organization", changes, {**fields, "domain": {}})
    with pytest.raises(AssertionError, match="none of"):
        assert_fields_correspond("organization", [*changes, {"field": "phone"}], fields)
    with pytest.raises(AssertionError):
        assert_fields_correspond("organization", changes, {**fields, "attributes.name": {}})
