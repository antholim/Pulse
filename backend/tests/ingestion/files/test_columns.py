# AI contribution: 50% or more AI-generated
"""The documented import columns and their template files."""

import pytest

from app.ingestion.files.columns import LAYOUTS, TEMPLATES
from app.ingestion.files.reader import read_file


@pytest.mark.parametrize("kind", sorted(LAYOUTS))
def test_each_template_has_exactly_the_documented_columns(kind):
    # Arrange
    header = TEMPLATES[kind].read_text(encoding="utf-8").splitlines()[0]

    # Act / Assert
    assert tuple(header.split(",")) == LAYOUTS[kind].columns


@pytest.mark.parametrize("kind", sorted(LAYOUTS))
def test_each_template_reads_as_a_valid_file_without_rows(kind):
    # Act / Assert
    assert read_file(TEMPLATES[kind].read_bytes(), "csv", LAYOUTS[kind]) == []


@pytest.mark.parametrize("kind", sorted(LAYOUTS))
def test_required_columns_are_documented_columns(kind):
    # Arrange
    layout = LAYOUTS[kind]

    # Act / Assert
    assert set(layout.required) | set(layout.one_of) <= set(layout.columns)
