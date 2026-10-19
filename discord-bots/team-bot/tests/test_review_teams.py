from pathlib import Path

import pytest

from team_bot.config import ConfigError
from team_bot.domain import review_teams as rt

BOT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BOT_ROOT.parents[1]

CONFIG = """
[teams.data]
name = "Data team"
discord_role_id = 111
members = ["alice", "@Bob"]
labels = ["data", "Entity Resolution"]
paths = ["backend/app/processing/", "backend/synthetic/"]

[teams.infra]
name = "Infra team"
members = ["carol", "bob"]
labels = ["infra"]
paths = [".github/", "**/Dockerfile", "compose.yaml"]
"""


@pytest.fixture
def teams():
    return rt.parse_review_teams(CONFIG)


def test_parse_review_teams(teams):
    data, infra = teams
    assert data.key == "data"
    assert data.members == ("alice", "Bob")  # a leading @ is dropped
    assert data.discord_role_id == 111
    assert infra.discord_role_id is None


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("not toml [", "not valid TOML"),
        ("[other]\nx = 1", "at least one [teams.<key>]"),
        ("teams = 1", "at least one [teams.<key>]"),
        ("[teams]\ndata = 1", "[teams.data] must be a table"),
        ('[teams.data]\nname = "D"\nmember = []\nlabels = ["x"]', "unknown keys: member"),
        ('[teams.data]\nlabels = ["x"]', "needs a name"),
        ('[teams.data]\nname = "D"\ndiscord_role_id = "1"\nlabels = ["x"]', "positive number"),
        ('[teams.data]\nname = "D"\nlabels = "x"', "labels must be a list"),
        ('[teams.data]\nname = "D"\nlabels = [""]', "labels must be a list"),
        ('[teams.data]\nname = "D"\nmembers = []', "at least one label or path"),
        ('[teams.data]\nname = "D"\npaths = ["/backend/"]', "must be relative"),
    ],
)
def test_parse_review_teams_rejects(text, message):
    with pytest.raises(ConfigError, match=message.replace("[", r"\[").replace(".", r"\.")):
        rt.parse_review_teams(text)


def test_load_review_teams_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="Cannot read"):
        rt.load_review_teams(tmp_path / "nope.toml")


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("frontend/", "frontend/src/App.tsx", True),
        ("frontend/", "frontend", False),
        ("frontend/", "backend/frontend/x.ts", False),
        ("compose.yaml", "compose.yaml", True),
        ("compose.yaml", "backend/compose.yaml", False),
        ("**/Dockerfile", "Dockerfile", True),
        ("**/Dockerfile", "backend/Dockerfile", True),
        ("**/Dockerfile", "backend/Dockerfile.dev", False),
        ("backend/*.py", "backend/main.py", True),
        ("backend/*.py", "backend/app/main.py", False),
        ("backend/**/test_?.py", "backend/a/b/test_x.py", True),
        ("docs/**", "docs/a/b.md", True),
        (".github/", ".github/workflows/ci.yml", True),
        (".github/", "xgithub/ci.yml", False),
    ],
)
def test_path_matches(pattern, path, expected):
    assert rt.path_matches(pattern, path) is expected


def test_match_teams_by_label_and_path(teams):
    matches = rt.match_teams(
        teams,
        labels=["entity resolution", "Release 1"],
        files=["backend/app/processing/cleaning.py", "README.md", "backend/Dockerfile"],
    )
    assert [m.team.key for m in matches] == ["data", "infra"]
    assert matches[0].labels == ("Entity Resolution",)
    assert matches[0].files == ("backend/app/processing/cleaning.py",)
    assert matches[1].labels == ()
    assert matches[1].files == ("backend/Dockerfile",)


def test_match_teams_none(teams):
    assert rt.match_teams(teams, ["Release 1"], ["README.md"]) == []


def test_reviewers_for_skips_author_and_duplicates(teams):
    matches = rt.match_teams(teams, ["data", "infra"], [])
    assert rt.reviewers_for(matches, author="ALICE") == ["Bob", "carol"]


def test_render_codeowners(teams):
    no_members = rt.ReviewTeam("swe", "SWE team", (), ("swe",), ("frontend/",))
    text = rt.render_codeowners([*teams, no_members])
    assert "/backend/app/processing/ @alice @Bob\n" in text
    assert "**/Dockerfile @carol @bob\n" in text
    assert "/compose.yaml @carol @bob\n" in text
    assert "# SWE team (no members listed yet)\n/frontend/\n" in text
    assert text.endswith("\n")


def test_repo_config_is_valid_and_codeowners_is_up_to_date():
    teams = rt.load_review_teams(BOT_ROOT / "review-teams.toml")
    assert {team.key for team in teams} == {"data", "swe", "infra"}
    codeowners = (REPO_ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
    assert codeowners.replace("\r\n", "\n") == rt.render_codeowners(teams), (
        "CODEOWNERS is out of date. From discord-bots/team-bot run: python -m team_bot.codeowners"
    )
