import pytest

from team_bot.domain.story_points import parse_story_points


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("**Parent epic:** #13\r\n**Story points:** 8\r\n\r\n## Goal", 8),
        ("**Story points**: 13", 13),
        ("**story points:**5", 5),
        ("No points here", None),
        ("Story points: 3", None),  # must be the bold line written by the generator
        ("", None),
        (None, None),
    ],
)
def test_parse_story_points(body, expected):
    assert parse_story_points(body) == expected
