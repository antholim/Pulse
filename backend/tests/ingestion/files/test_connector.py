# AI contribution: 50% or more AI-generated
"""Validating import rows and yielding the valid ones as raw records."""

import pytest

from app.ingestion.connector import RawRecord
from app.ingestion.files.connector import FileConnector, RejectedRow
from app.ingestion.files.reader import ImportFileError
from app.ingestion.mapped import MappingFailure

ORG_HEADER = "id,name,website,linkedin,email,phone,city"


def csv_bytes(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode()


def org_file(*rows: str) -> FileConnector:
    return FileConnector(csv_bytes(ORG_HEADER, *rows), "organizations.csv", "organization")


def test_valid_rows_become_raw_records_keyed_by_kind_and_id():
    # Arrange
    connector = org_file("42,Acme,acme.ca,,info@acme.ca,418 555 0100,Québec")

    # Act
    records = list(connector.fetch_since(None))

    # Assert
    assert records == [
        RawRecord(
            entity_kind="organization",
            external_id="organization:42",
            updated_at=None,
            payload={
                "id": "42",
                "name": "Acme",
                "website": "acme.ca",
                "linkedin": None,
                "email": "info@acme.ca",
                "phone": "418 555 0100",
                "city": "Québec",
            },
        )
    ]
    assert connector.rejected == []


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        (",Acme,,,,,", "id is missing"),
        ("1,,,,,,", "name is missing"),
        ("1,Acme,not a site,,,,", "website is not a web address"),
        (
            "1,Acme,,https://example.com/acme,,,",
            "linkedin is not a LinkedIn company or profile URL",
        ),
        ("1,Acme,,,info-at-acme.ca,,", "email is not an email address"),
        ("1,Acme,,,,call us,", "phone is not a phone number"),
        ("1,Acme,,,,,,extra", "row has more values than the header has columns"),
    ],
)
def test_an_invalid_row_is_rejected_with_its_row_number_and_reason(row, reason):
    # Arrange
    connector = org_file("9,Valid inc.,,,,,", row)

    # Act
    records = list(connector.fetch_since(None))

    # Assert
    assert [r.external_id for r in records] == ["organization:9"]
    assert connector.rejected == [RejectedRow(3, reason, None if row.startswith(",") else "1")]


def test_a_repeated_id_keeps_the_first_row_and_rejects_the_others():
    # Arrange
    connector = org_file("1,Acme,,,,,", "1,Acme bis,,,,,")

    # Act
    records = list(connector.fetch_since(None))

    # Assert
    assert [r.payload["name"] for r in records] == ["Acme"]
    assert connector.rejected == [RejectedRow(3, "id 1 is already used on row 2", "1")]


def test_a_person_needs_a_first_or_last_name():
    # Arrange
    data = csv_bytes("id,first_name,last_name", "p1,,Roy", "p2,,")
    connector = FileConnector(data, "people.csv", "person")

    # Act
    records = list(connector.fetch_since(None))

    # Assert
    assert [r.external_id for r in records] == ["person:p1"]
    assert connector.rejected == [RejectedRow(3, "first_name or last_name is needed", "p2")]


def test_rejected_rows_become_failures_named_by_their_id_or_their_row():
    # Arrange
    connector = org_file(",Acme,,,,,", "7,Acme,,,bad,,")
    list(connector.fetch_since(None))

    # Act
    failures = connector.failures()

    # Assert
    assert failures == [
        MappingFailure("organization", "row 2", "row 2: id is missing"),
        MappingFailure("organization", "organization:7", "row 3: email is not an email address"),
    ]


def test_the_whole_file_is_kept_as_one_record_named_by_the_file():
    # Arrange
    data = "\ufeffid,name\n1,Société Acme\n2,\n".encode()
    connector = FileConnector(data, "exports/organizations.csv", "organization")

    # Act
    record = connector.file_record()

    # Assert
    assert record == RawRecord(
        "import_file",
        "organizations.csv",
        None,
        {"filename": "organizations.csv", "format": "csv", "text": "id,name\n1,Société Acme\n2,\n"},
    )


def test_reading_twice_reports_each_rejected_row_once():
    # Arrange
    connector = org_file(",Acme,,,,,")

    # Act
    list(connector.fetch_since(None))
    list(connector.fetch_since(None))

    # Assert
    assert len(connector.rejected) == 1


def test_an_unknown_entity_kind_is_rejected():
    # Act / Assert
    with pytest.raises(ImportFileError, match="cannot import project files"):
        FileConnector(b"id\n", "projects.csv", "project")
