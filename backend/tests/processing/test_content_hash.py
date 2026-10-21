from dataclasses import replace

from app.ingestion.omerlo.mapping.mappers import MappedRecord
from app.processing.content_hash import content_hash, without_volatile


def organization(**attributes) -> MappedRecord:
    return MappedRecord(
        kind="organization",
        external_id="org-1",
        workspace_id="ws-1",
        name_normalized="groupe exemple",
        domain="exemple.ca",
        attributes={"name": "Groupe Exemple", "updated_at": "2026-10-01T00:00:00Z", **attributes},
    )


def test_the_same_content_hashes_the_same_whatever_the_key_order():
    # Arrange
    first = organization(a=1, b=2)
    second = replace(first, attributes=dict(reversed(first.attributes.items())))

    # Act
    digests = {content_hash(first), content_hash(second)}

    # Assert
    assert len(digests) == 1
    assert len(digests.pop()) == 64


def test_a_new_updated_at_alone_is_not_a_change():
    # Arrange
    record = organization(contact=[{"email": "a@exemple.ca", "updated_at": "2026-10-01"}])
    refetched = organization(contact=[{"email": "a@exemple.ca", "updated_at": "2026-10-09"}])
    refetched.attributes["updated_at"] = "2026-10-09T00:00:00Z"

    # Act
    same = content_hash(record) == content_hash(refetched)

    # Assert
    assert same


def test_a_changed_payload_field_is_a_change():
    # Arrange
    before, after = organization(phone="1"), organization(phone="2")

    # Act
    same = content_hash(before) == content_hash(after)

    # Assert
    assert not same


def test_a_changed_normalized_column_is_a_change():
    # Arrange
    record = organization()
    changed = [
        replace(record, domain="autre.ca"),
        replace(record, name_normalized="autre nom"),
        replace(record, linkedin="company/autre"),
        replace(record, workspace_id="ws-2"),
        replace(record, external_ids={"crm_id": ["CRM-1"]}),
        replace(record, kind="person"),
    ]

    # Act
    digests = {content_hash(other) for other in changed}

    # Assert
    assert content_hash(record) not in digests
    assert len(digests) == len(changed)


def test_volatile_keys_are_dropped_at_any_depth():
    # Arrange
    value = {"updated_at": 1, "list": [{"updated_at": 2, "keep": 3}], "keep": 4}

    # Act
    stripped = without_volatile(value)

    # Assert
    assert stripped == {"list": [{"keep": 3}], "keep": 4}
