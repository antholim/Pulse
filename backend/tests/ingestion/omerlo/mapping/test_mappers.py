import pytest

from app.ingestion.omerlo.mapping.mappers import MappingError, map_record
from tests.ingestion.omerlo.mapping import payloads
from tests.ingestion.omerlo.mapping.payloads import WORKSPACE_ID, contact, profiles_block

CRM_METADATA = [{"key": "crm_id", "value": "CRM-0042"}, {"key": "crm_id", "value": "CRM-0042"}]


# --------------------------------------------------------------- organization


def test_organization_identifiers_come_from_every_locale_deduplicated():
    # Arrange
    payload = payloads.organization()

    # Act
    record = map_record("organization", payload)

    # Assert
    assert record.kind == "organization"
    assert record.external_id == "org-1"
    assert record.workspace_id == WORKSPACE_ID
    assert record.name_normalized == "boulangerie saint roch"
    assert record.domain == "boulangeriestroch.ca"
    assert record.linkedin == "company/boulangerie-st-roch"
    assert record.attributes["identifiers"] == {
        "emails": ["info@boulangeriestroch.ca"],
        "phones": ["+14185550142"],
        "domains": ["boulangeriestroch.ca"],
        "linkedin": ["company/boulangerie-st-roch"],
    }
    assert record.attributes["cities"] == ["quebec", "quebec city"]


def test_organization_domain_never_comes_from_the_canonical_url():
    # Arrange
    payload = payloads.organization()
    payload["contact"] = [contact("fr", email="info@boulangeriestroch.ca")]

    # Act
    record = map_record("organization", payload)

    # Assert
    assert record.domain is None
    assert record.attributes["identifiers"]["domains"] == []


def test_organization_keeps_the_whole_payload_in_attributes():
    # Arrange
    payload = payloads.organization()

    # Act
    attributes = map_record("organization", payload).attributes

    # Assert
    assert {key: attributes[key] for key in payload if key != "id"} == {
        key: value for key, value in payload.items() if key != "id"
    }


def test_metadata_pairs_become_external_ids():
    # Arrange
    metadata = [*CRM_METADATA, {"key": "neq", "value": " 1234567890 "}]

    # Act
    record = map_record("organization", payloads.organization(), metadata=metadata)

    # Assert
    assert record.external_ids == {"crm_id": ["CRM-0042"], "neq": ["1234567890"]}


def test_malformed_metadata_entries_are_skipped():
    # Arrange
    metadata = ["crm_id", {"key": "crm_id"}, {"key": " ", "value": "x"}, {"key": 1, "value": 2}]

    # Act
    record = map_record("organization", payloads.organization(), metadata=metadata)

    # Assert
    assert record.external_ids == {}


def test_deleted_contact_locales_give_no_identifiers():
    # Arrange
    payload = payloads.organization()
    payload["contact"] = [
        contact("fr", website="https://ancien-site.ca", deleted_at="2026-01-01T00:00:00Z")
    ]

    # Act
    record = map_record("organization", payload)

    # Assert
    assert record.domain is None
    assert record.attributes["identifiers"]["domains"] == []


def test_invalid_contact_values_are_dropped_from_identifiers():
    # Arrange
    payload = payloads.organization()
    payload["contact"] = [
        contact("fr", email="not-an-email", phone="12", website=42, linkedin="https://x.example/a"),
        "not a contact",
    ]

    # Act
    identifiers = map_record("organization", payload).attributes["identifiers"]

    # Assert
    assert identifiers == {"emails": [], "phones": [], "domains": [], "linkedin": []}


@pytest.mark.parametrize("key", ["contact", "address", "profile"])
@pytest.mark.parametrize("value", [None, "oops", 3])
def test_missing_or_malformed_optional_parts_read_as_empty(key, value):
    # Arrange
    payload = payloads.organization()
    payload[key] = value

    # Act
    record = map_record("organization", payload)

    # Assert
    assert record.name_normalized == "boulangerie saint roch"
    if key == "profile":
        assert record.workspace_id is None


@pytest.mark.parametrize("name", [None, "", "   ", 7])
def test_organization_without_a_name_fails(name):
    # Arrange
    payload = payloads.organization()
    payload["name"] = name

    # Act / Assert
    with pytest.raises(MappingError, match="no name"):
        map_record("organization", payload)


# --------------------------------------------------------------------- person


def test_person_keeps_only_the_minimal_fields():
    # Arrange
    payload = payloads.person()

    # Act
    record = map_record("person", payload, metadata=CRM_METADATA)

    # Assert
    assert record.name_normalized == "marie eve tremblay"
    assert record.linkedin == "in/marie-eve-tremblay"
    assert record.domain is None
    assert record.workspace_id == WORKSPACE_ID
    assert record.external_ids == {"crm_id": ["CRM-0042"]}
    assert record.attributes == {
        "first_name": "Marie-Ève",
        "last_name": "Tremblay",
        "job_titles": {"fr": "Directrice générale", "en": "General Manager"},
        "identifiers": {
            "emails": ["marie-eve@boulangeriestroch.ca"],
            "linkedin": ["in/marie-eve-tremblay"],
        },
    }


def test_person_with_only_one_name_part_is_mapped():
    # Arrange
    payload = payloads.person()
    payload["first_name"] = None

    # Act
    record = map_record("person", payload)

    # Assert
    assert record.name_normalized == "tremblay"


def test_person_without_any_name_fails():
    # Arrange
    payload = payloads.person()
    payload["first_name"] = payload["last_name"] = " "

    # Act / Assert
    with pytest.raises(MappingError, match="person has no name"):
        map_record("person", payload)


# ---------------------------------------------------------- project and event


@pytest.mark.parametrize(
    ("kind", "builder", "expected_name"),
    [
        ("project", payloads.project, "corridor vert"),
        ("event", payloads.event, "festival d ete"),
    ],
)
def test_named_profiles_take_the_first_locale_name(kind, builder, expected_name):
    # Arrange
    payload = builder()

    # Act
    record = map_record(kind, payload)

    # Assert
    assert record.kind == kind
    assert record.name_normalized == expected_name
    assert record.workspace_id == WORKSPACE_ID
    assert record.attributes["locales"] == builder()["locales"]


def test_only_organizations_fill_the_matching_columns():
    # Arrange
    payload = payloads.project()

    # Act
    record = map_record("project", payload)

    # Assert
    assert record.domain is None
    assert record.linkedin is None
    assert record.attributes["identifiers"]["domains"] == ["corridorvert.ca"]
    assert record.attributes["owner_id"] == "org-1"


def test_deleted_or_blank_locales_are_skipped_for_the_name():
    # Arrange
    payload = payloads.event()
    payload["locales"][0]["deleted_at"] = "2026-01-01T00:00:00Z"

    # Act
    record = map_record("event", payload)

    # Assert
    assert record.name_normalized == "summer festival"


def test_named_profile_without_locales_has_no_name():
    # Arrange
    payload = payloads.project()
    payload["locales"] = None

    # Act
    record = map_record("project", payload)

    # Assert
    assert record.name_normalized is None


# -------------------------------------------------------------------- content


def test_content_keeps_flags_publication_and_linked_profiles():
    # Arrange
    blocks = [
        profiles_block("organization", "org-1", "org-2"),
        profiles_block("person", "person-1", "person-1"),
        {"kind": "richtext", "content_html": "<p>Texte</p>"},
    ]

    # Act
    record = map_record("content", payloads.content(), blocks=blocks)

    # Assert
    assert record.kind == "content"
    assert record.workspace_id == WORKSPACE_ID
    assert record.name_normalized == "la boulangerie ses 100 ans"
    assert record.domain is None
    assert record.attributes["is_sponsored"] is True
    assert record.attributes["is_advertising"] is False
    assert record.attributes["published_at"] == "2026-10-10T14:30:00+00:00"
    assert record.attributes["author_profile_ids"] == ["person-9"]
    assert record.attributes["linked_profiles"] == {
        "organization": ["org-1", "org-2"],
        "person": ["person-1"],
    }


@pytest.mark.parametrize(
    ("title_html", "expected_name"),
    [
        ("<h1><b>Hel</b>lo <em>Québec</em></h1>", "hello quebec"),
        ("<h1>Un<br>Deux</h1>", "un deux"),
        ("<h1>Un</h1><p>Deux</p>", "un deux"),
    ],
)
def test_content_title_keeps_words_split_only_by_breaking_tags(title_html, expected_name):
    # Arrange
    payload = payloads.content()
    payload["locales"][0]["title_html"] = title_html

    # Act
    record = map_record("content", payload)

    # Assert
    assert record.name_normalized == expected_name


def test_content_with_malformed_fields_keeps_what_it_can():
    # Arrange
    payload = payloads.content()
    payload |= {"is_sponsored": "yes", "published_at": "last week", "locales": [{"authors": 1}]}
    blocks = [{"kind": "profiles", "profile_kind": "person", "profile_entries": "x"}, None]

    # Act
    attributes = map_record("content", payload, blocks=blocks).attributes

    # Assert
    assert attributes["is_sponsored"] is None
    assert attributes["published_at"] is None
    assert attributes["author_profile_ids"] == []
    assert attributes["linked_profiles"] == {}


# ------------------------------------------------------------------- dispatch


@pytest.mark.parametrize("record_id", [None, "", 12.5, True])
def test_payload_without_a_usable_id_fails(record_id):
    # Arrange
    payload = payloads.project()
    payload["id"] = record_id

    # Act / Assert
    with pytest.raises(MappingError, match="no id"):
        map_record("project", payload)


def test_numeric_ids_are_read_as_strings():
    # Arrange
    payload = payloads.project()
    payload["id"] = 42

    # Act
    record = map_record("project", payload)

    # Assert
    assert record.external_id == "42"


def test_payload_that_is_not_an_object_fails():
    # Act / Assert
    with pytest.raises(MappingError, match="not a JSON object"):
        map_record("organization", ["org-1"])


def test_unknown_kind_fails():
    # Act / Assert
    with pytest.raises(MappingError, match="no mapper"):
        map_record("workspace", {"id": "ws-1"})
