# AI contribution: 50% or more AI-generated
"""Mapping valid import rows to source records."""

from app.ingestion.connector import RawRecord
from app.ingestion.files.mapping import map_rows
from app.ingestion.mapped import MappingFailure


def raw(kind, values):
    return RawRecord(kind, f"{kind}:{values['id']}", None, values)


def test_an_organization_row_fills_the_matching_columns():
    # Arrange
    row = {
        "id": "42",
        "name": "Acme Inc.",
        "website": "https://www.Acme.qc.ca/a-propos",
        "linkedin": "linkedin.com/company/acme",
        "email": "Info@Acme.qc.ca",
        "phone": "418 555 0100",
        "city": "Ville de Québec",
        "sector": "media",
    }

    # Act
    [record] = map_rows([raw("organization", row)]).records

    # Assert
    assert record.kind == "organization"
    assert record.external_id == "organization:42"
    assert record.workspace_id is None
    assert record.name_normalized == "acme"
    assert (record.domain, record.linkedin, record.city) == ("acme.qc.ca", "company/acme", "quebec")
    assert record.attributes["sector"] == "media"
    assert record.attributes["identifiers"] == {
        "emails": ["info@acme.qc.ca"],
        "phones": ["+14185550100"],
        "domains": ["acme.qc.ca"],
        "linkedin": ["company/acme"],
    }
    assert "id" not in record.attributes


def test_a_person_row_joins_the_first_and_last_name():
    # Arrange
    row = {"id": "p1", "first_name": "Marie-Ève", "last_name": "Roy", "email": "me@roy.ca"}

    # Act
    [record] = map_rows([raw("person", row)]).records

    # Assert
    assert record.name_normalized == "marie eve roy"
    assert record.domain is None
    assert record.attributes["identifiers"] == {"emails": ["me@roy.ca"], "linkedin": []}


def test_rejected_rows_are_reported_after_the_rows_that_fail_cleaning():
    # Arrange
    rejected = MappingFailure(
        "organization", "organization:7", "row 5: email is not an email address"
    )

    # Act
    result = map_rows([raw("organization", {"id": "8", "name": "Inc."})], rejected=[rejected])

    # Assert
    assert result.records == ()
    assert result.failures == (
        MappingFailure(
            "organization", "organization:8", "cleaning removed required fields: name_normalized"
        ),
        rejected,
    )
