from pathlib import Path

import pytest

from team_bot.config import ConfigError
from team_bot.domain import review_teams as rt

BOT_ROOT = Path(__file__).resolve().parents[1]

CONFIG = """
[teams.data]
name = "Data team"
discord_role = "@Data Team"
members = ["alice", "@Bob"]
labels = ["data", "Entity Resolution"]

[teams.infra]
name = "Infra team"
members = ["carol", "bob"]
labels = ["infra"]
"""


@pytest.fixture
def teams():
    return rt.parse_review_teams(CONFIG)


def test_parse_review_teams(teams):
    data, infra = teams
    assert data.key == "data"
    assert data.members == ("alice", "Bob")  # a leading @ is dropped
    assert data.discord_role == "Data Team"  # a leading @ is dropped
    assert infra.discord_role is None
    by_id = rt.parse_review_teams('[teams.x]\nname = "X"\ndiscord_role = 5\nlabels = ["x"]')
    assert by_id[0].discord_role == 5


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("not toml [", "not valid TOML"),
        ("[other]\nx = 1", "at least one [teams.<key>]"),
        ("teams = 1", "at least one [teams.<key>]"),
        ("[teams]\ndata = 1", "[teams.data] must be a table"),
        ('[teams.data]\nname = "D"\nmember = []\nlabels = ["x"]', "unknown keys: member"),
        ('[teams.data]\nlabels = ["x"]', "needs a name"),
        ('[teams.data]\nname = "D"\ndiscord_role = ""\nlabels = ["x"]', "role name or a role ID"),
        ('[teams.data]\nname = "D"\ndiscord_role = 0\nlabels = ["x"]', "role name or a role ID"),
        ('[teams.data]\nname = "D"\ndiscord_role = true\nlabels = ["x"]', "role name or a role ID"),
        ('[teams.data]\nname = "D"\nlabels = "x"', "labels must be a list"),
        ('[teams.data]\nname = "D"\nlabels = [""]', "labels must be a list"),
        ('[teams.data]\nname = "D"\nmembers = []', "at least one label"),
        ('[teams.data]\nname = "D"\nlabels = ["x"]\npaths = ["a/"]', "unknown keys: paths"),
    ],
)
def test_parse_review_teams_rejects(text, message):
    with pytest.raises(ConfigError, match=message.replace("[", r"\[").replace(".", r"\.")):
        rt.parse_review_teams(text)


def test_load_review_teams_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="Cannot read"):
        rt.load_review_teams(tmp_path / "nope.toml")


def test_match_teams_by_label(teams):
    matches = rt.match_teams(teams, labels=["entity resolution", "Release 1"])
    assert [m.team.key for m in matches] == ["data"]
    assert matches[0].labels == ("Entity Resolution",)


def test_match_teams_without_team_label_is_every_team(teams):
    matches = rt.match_teams(teams, ["Release 1"])
    assert [m.team.key for m in matches] == ["data", "infra"]
    assert all(m.labels == () for m in matches)


def test_reviewers_for_skips_author_and_duplicates(teams):
    matches = rt.match_teams(teams, ["data", "infra"])
    assert rt.reviewers_for(matches, author="ALICE") == ["Bob", "carol"]


def test_repo_config_is_valid():
    teams = rt.load_review_teams(BOT_ROOT / "review-teams.toml")
    assert {team.key for team in teams} == {"data", "swe", "infra"}
