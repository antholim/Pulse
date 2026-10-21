from dataclasses import replace

import pytest

from app.ingestion.omerlo.mapping.mappers import MappedRecord
from app.processing.content_hash import content_hash
from app.processing.record_diff import (
    COMPARED_FIELDS,
    IGNORED_FIELDS,
    diff_snapshots,
    field_changes,
    snapshot,
)
from synthetic.mutate import DEMO, mutate
from synthetic.omerlo_fixtures import OmerloFixtureGenerator
from tests.fixture_diff import assert_fields_correspond, expected, mapped_records
from tests.synthetic.conftest import SMALL


def organization(**attributes) -> MappedRecord:
    return MappedRecord(
        kind="organization",
        external_id="org-1",
        workspace_id="ws-1",
        name_normalized="groupe exemple",
        domain="exemple.ca",
        attributes={"name": "Groupe Exemple", "updated_at": "2026-10-01T00:00:00Z", **attributes},
    )


def contact(locale: str, phone: str, **fields) -> dict:
    return {"locale": locale, "phone": phone, "updated_at": "2026-10-01T00:00:00Z", **fields}


def test_a_changed_column_gives_its_before_and_after_values():
    # Arrange
    before = snapshot(organization())
    after = snapshot(replace(organization(), domain="exemple.com"))

    # Act
    changes = field_changes(before, after)

    # Assert
    assert changes == {"domain": {"before": "exemple.ca", "after": "exemple.com"}}


def test_nested_attributes_are_compared_leaf_by_leaf():
    # Arrange
    before = snapshot(organization(profile={"canonical_url": "https://a.ca", "type": 1}))
    after = snapshot(organization(profile={"canonical_url": "https://b.ca", "type": 1}))

    # Act
    changes = field_changes(before, after)

    # Assert
    assert changes == {
        "attributes.profile.canonical_url": {"before": "https://a.ca", "after": "https://b.ca"}
    }


def test_per_locale_lists_are_keyed_by_locale():
    # Arrange
    before = snapshot(organization(contact=[contact("fr", "1"), contact("en", "2")]))
    after = snapshot(organization(contact=[contact("en", "3"), contact("fr", "1")]))

    # Act
    changes = field_changes(before, after)

    # Assert
    assert changes == {"attributes.contact[en].phone": {"before": "2", "after": "3"}}


def test_a_locale_added_or_dropped_shows_its_whole_entry():
    # Arrange
    before = snapshot(organization(contact=[contact("fr", "1")]))
    after = snapshot(organization(contact=[contact("fr", "1"), contact("en", "2")]))

    # Act
    changes = field_changes(before, after)

    # Assert
    assert changes == {
        "attributes.contact[en]": {"before": None, "after": {"locale": "en", "phone": "2"}}
    }


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ([{"locale": "fr", "phone": "1"}, {"locale": "fr", "phone": "2"}], [{"locale": "fr"}]),
        (["a.ca", "b.ca"], ["b.ca"]),
        ([], [{"locale": "fr"}]),
    ],
)
def test_other_lists_are_one_value(before, after):
    # Act
    changes = field_changes({"value": before}, {"value": after})

    # Assert
    assert changes == {"value": {"before": before, "after": after}}


def test_ignored_fields_are_dropped_at_any_depth():
    # Arrange
    before = organization(contact=[contact("fr", "1")], profile={"updated_at": "2026-10-01"})
    after = replace(
        before,
        attributes={
            **before.attributes,
            "updated_at": "2026-10-09T00:00:00Z",
            "contact": [{**contact("fr", "1"), "updated_at": "2026-10-09T00:00:00Z"}],
            "profile": {"updated_at": "2026-10-09"},
        },
    )

    # Act
    changes = field_changes(snapshot(before), snapshot(after))
    raw = field_changes({"updated_at": 1, "a": {"updated_at": 1}}, {"updated_at": 2, "a": {}})

    # Assert
    assert changes == raw == {}
    assert "updated_at" in IGNORED_FIELDS


@pytest.mark.parametrize(
    "change",
    [
        {"name_normalized": "autre nom"},
        {"workspace_id": "ws-2"},
        {"external_ids": {"crm_id": ["CRM-1"]}},
        {"attributes": {"name": "Autre"}},
        {"attributes": {"name": "Groupe Exemple", "updated_at": "2026-10-09T00:00:00Z"}},
    ],
)
def test_a_diff_is_empty_exactly_when_the_content_hash_is_unchanged(change):
    # Arrange
    before = organization()
    after = replace(before, **change)

    # Act
    changes = field_changes(snapshot(before), snapshot(after))

    # Assert
    assert (changes == {}) == (content_hash(before) == content_hash(after))
    assert set(COMPARED_FIELDS) >= {path.split(".")[0] for path in changes}


def test_snapshots_are_sorted_into_added_modified_and_removed():
    # Arrange
    before = {"a": {"name": "un"}, "b": {"name": "deux"}, "c": {"name": "trois"}}
    after = {"b": {"name": "deux"}, "c": {"name": "trois!"}, "d": {"name": "quatre"}}

    # Act
    diff = diff_snapshots(before, after)

    # Assert
    assert diff.added == ["d"]
    assert diff.removed == ["a"]
    assert diff.modified == {"c": {"name": {"before": "trois", "after": "trois!"}}}


def test_the_demo_mutation_set_gives_exactly_its_expected_diff_once_mapped():
    # Arrange
    before = OmerloFixtureGenerator(5, SMALL).generate()
    after, expected_diff = mutate(before, DEMO)

    for old, new in zip(before, after, strict=True):
        wanted = expected(expected_diff["tenants"][old.tenant.slug])
        kinds = {r.external_id: r.kind for r in mapped_records(old) + mapped_records(new)}

        # Act
        diff = diff_snapshots(
            {r.external_id: snapshot(r) for r in mapped_records(old)},
            {r.external_id: snapshot(r) for r in mapped_records(new)},
        )

        # Assert
        assert {(kinds[i], i) for i in diff.added} == wanted.added
        assert {(kinds[i], i) for i in diff.removed} == wanted.removed
        assert {(kinds[i], i) for i in diff.modified} == set(wanted.modified)
        for external_id, fields in diff.modified.items():
            key = (kinds[external_id], external_id)
            assert_fields_correspond(key[0], wanted.modified[key], fields)
