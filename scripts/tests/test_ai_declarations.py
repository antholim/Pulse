# AI contribution: 50% or more AI-generated
import pytest
from ai_declarations import added_to_pending, malformed_line


@pytest.mark.parametrize(
    "head",
    [
        ["# AI contribution: Below 50% AI-generated", "import os"],
        ["// AI contribution: No substantial AI-generated code"],
        ["#!/usr/bin/env python", "# AI contribution: 50% or more AI-generated"],
        ["import os", "", "def main():"],
    ],
)
def test_a_valid_or_missing_declaration_is_not_malformed(head):
    # Act / Assert
    assert malformed_line(head) is None


@pytest.mark.parametrize(
    "line",
    [
        "# AI declaration: Below 50% AI-generated",
        "AI declaration: Below 50% AI",
        "# AI contribution: below 50% AI-generated",
        "# AI contribution: Below 50%",
        "#AI contribution: Below 50% AI-generated",
        "# AI contribution: Below 50% AI-generated (only the tests)",
    ],
)
def test_a_line_that_looks_like_a_declaration_but_is_not_one_is_malformed(line):
    # Arrange
    head = ['"""', line, '"""']

    # Act
    result = malformed_line(head)

    # Assert
    assert result == line


def test_a_malformed_line_is_reported_even_next_to_a_valid_one():
    # Arrange
    head = ["# AI contribution: Below 50% AI-generated", "# AI declaration: Below 50% AI"]

    # Act
    result = malformed_line(head)

    # Assert
    assert result == "# AI declaration: Below 50% AI"


def test_paths_missing_from_the_base_pending_list_count_as_added():
    # Arrange
    base = {"backend/app/a.py", "backend/app/b.py"}
    current = {"backend/app/b.py", "backend/app/new.py"}

    # Act
    result = added_to_pending(current, base)

    # Assert
    assert result == ["backend/app/new.py"]


def test_removing_paths_from_the_pending_list_is_allowed():
    # Arrange
    base = {"backend/app/a.py", "backend/app/b.py"}
    current = {"backend/app/a.py"}

    # Act
    result = added_to_pending(current, base)

    # Assert
    assert result == []
