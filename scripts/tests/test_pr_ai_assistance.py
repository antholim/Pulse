# AI contribution: 50% or more AI-generated
import pytest
from pr_ai_assistance import problems

TEMPLATE_COMMENT = """<!-- Required by SOEN 490.
     Pick one level for the code this PR adds or changes:
     No substantial AI-generated code | Below 50% AI-generated | 50% or more AI-generated
     List the files AI substantially helped with, and say in one sentence what it did. -->"""


def body(section: str) -> str:
    return f"## Summary\nDoes a thing.\n\n## AI assistance\n{TEMPLATE_COMMENT}\n{section}\n"


def test_a_filled_in_section_with_files_passes():
    # Arrange
    text = body(
        "AI contribution: Below 50% AI-generated\n\n"
        "AI-assisted files:\n- backend/app/sync.py\n\n"
        "Claude Code drafted the tests."
    )

    # Act / Assert
    assert problems(text) == []


def test_no_substantial_ai_needs_no_files():
    # Arrange
    text = body("AI contribution: No substantial AI-generated code\n\nAI-assisted files:\n-")

    # Act / Assert
    assert problems(text) == []


def test_bold_labels_and_backticks_are_accepted():
    # Arrange
    text = body(
        "**AI contribution:** `50% or more AI-generated`\n\n"
        "**AI-assisted files:**\n- `scripts/ai_declarations.py`"
    )

    # Act / Assert
    assert problems(text) == []


@pytest.mark.parametrize("text", ["", None, "## Summary\nDoes a thing."])
def test_a_missing_section_fails(text):
    # Act
    result = problems(text)

    # Assert
    assert result == ['The PR description has no "## AI assistance" section.']


def test_the_unfilled_template_fails():
    # Arrange
    text = body("AI contribution:\n\nAI-assisted files:\n-")

    # Act
    result = problems(text)

    # Assert
    assert result == [
        '"AI contribution:" must be exactly one of: No substantial AI-generated code, '
        "Below 50% AI-generated, 50% or more AI-generated."
    ]


def test_more_than_one_level_fails():
    # Arrange
    text = body("AI contribution: Below 50% AI-generated | 50% or more AI-generated")

    # Act
    result = problems(text)

    # Assert
    assert len(result) == 1
    assert result[0].startswith('"AI contribution:" must be exactly one of')


def test_ai_generated_code_without_files_fails():
    # Arrange
    text = body("AI contribution: 50% or more AI-generated\n\nAI-assisted files:\n-")

    # Act
    result = problems(text)

    # Assert
    assert result == ['List at least one file under "AI-assisted files:".']


def test_windows_line_endings_are_accepted():
    # Arrange
    text = body("AI contribution: Below 50% AI-generated\n\nAI-assisted files:\n- a.py").replace(
        "\n", "\r\n"
    )

    # Act / Assert
    assert problems(text) == []
