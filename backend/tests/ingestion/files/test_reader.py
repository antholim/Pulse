# AI contribution: 50% or more AI-generated
"""Reading import files into numbered rows."""

import json

import pytest

from app.ingestion.files.columns import LAYOUTS
from app.ingestion.files.reader import FileRow, ImportFileError, file_format, read_file

ORGANIZATIONS = LAYOUTS["organization"]


def csv_bytes(*lines: str, encoding: str = "utf-8") -> bytes:
    return ("\n".join(lines) + "\n").encode(encoding)


def test_csv_rows_are_numbered_like_spreadsheet_rows():
    # Arrange
    data = csv_bytes("id,name,city", "1,Acme,Québec", "", "2,Beta,Lévis")

    # Act
    rows = read_file(data, "csv", ORGANIZATIONS)

    # Assert
    assert rows == [
        FileRow(2, {"id": "1", "name": "Acme", "city": "Québec"}),
        FileRow(4, {"id": "2", "name": "Beta", "city": "Lévis"}),
    ]


def test_semicolon_separators_and_a_byte_order_mark_are_read():
    # Arrange
    data = "\ufeffid;name;city\n1;Acme inc.;Québec\n".encode()

    # Act
    [row] = read_file(data, "csv", ORGANIZATIONS)

    # Assert
    assert row.values == {"id": "1", "name": "Acme inc.", "city": "Québec"}


def test_headers_are_matched_without_case_or_spaces_and_blank_values_become_none():
    # Arrange
    data = csv_bytes(" ID , Name ,Website", "1, Acme ,")

    # Act
    [row] = read_file(data, "csv", ORGANIZATIONS)

    # Assert
    assert row.values == {"id": "1", "name": "Acme", "website": None}


def test_a_row_with_more_values_than_columns_is_marked():
    # Arrange
    data = csv_bytes("id,name", "1,Acme,extra")

    # Act
    [row] = read_file(data, "csv", ORGANIZATIONS)

    # Assert
    assert row.problem == "row has more values than the header has columns"


def test_a_csv_without_a_required_column_is_rejected():
    # Arrange
    data = csv_bytes("id,website", "1,acme.ca")

    # Act / Assert
    with pytest.raises(ImportFileError, match="missing required columns: name"):
        read_file(data, "csv", ORGANIZATIONS)


def test_a_people_csv_needs_at_least_one_name_column():
    # Arrange
    data = csv_bytes("id,email", "1,jean@exemple.ca")

    # Act / Assert
    with pytest.raises(ImportFileError, match="one of the columns: first_name, last_name"):
        read_file(data, "csv", LAYOUTS["person"])


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "file is empty"),
        (csv_bytes("id,name,id", "1,Acme,2"), "repeated column: id"),
        ("id,name\n1,Société\n".encode("cp1252"), "not UTF-8"),
    ],
)
def test_unreadable_csv_files_are_rejected(data, message):
    # Act / Assert
    with pytest.raises(ImportFileError, match=message):
        read_file(data, "csv", ORGANIZATIONS)


def test_json_entries_are_numbered_from_one_and_numbers_read_as_text():
    # Arrange
    data = json.dumps([{"id": 7, "Name": "Acme"}, {"id": "8", "name": "Beta"}]).encode()

    # Act
    rows = read_file(data, "json", ORGANIZATIONS)

    # Assert
    assert rows == [
        FileRow(1, {"id": "7", "name": "Acme"}),
        FileRow(2, {"id": "8", "name": "Beta"}),
    ]


@pytest.mark.parametrize(
    ("entry", "problem"),
    [
        ("not an object", "entry is not a JSON object"),
        ({"id": "1", "name": ["Acme"]}, "value of name is not text or a number"),
    ],
)
def test_a_json_entry_that_cannot_be_a_row_is_marked(entry, problem):
    # Arrange
    data = json.dumps([entry]).encode()

    # Act
    [row] = read_file(data, "json", ORGANIZATIONS)

    # Assert
    assert (row.number, row.problem) == (1, problem)


@pytest.mark.parametrize("data", [b"{}", b"[1,", b'"rows"'])
def test_json_that_is_not_a_list_is_rejected(data):
    # Act / Assert
    with pytest.raises(ImportFileError, match="JSON list of objects"):
        read_file(data, "json", ORGANIZATIONS)


@pytest.mark.parametrize(("name", "expected"), [("orgs.CSV", "csv"), ("people.json", "json")])
def test_the_format_comes_from_the_file_extension(name, expected):
    # Act / Assert
    assert file_format(name) == expected


def test_other_extensions_are_rejected():
    # Act / Assert
    with pytest.raises(ImportFileError, match=r"only \.csv and \.json"):
        file_format("orgs.xlsx")
