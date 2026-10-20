"""Which team reviews a pull request (issue #76).

Teams live in `review-teams.toml`: GitHub usernames, an optional Discord role, and the
labels each team owns. A PR goes to every team whose labels are on it (or on an issue it
closes). A PR without any team's label goes to every team.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from team_bot.config import ConfigError

TEAM_KEYS = {"name", "discord_role", "members", "labels"}


@dataclass(frozen=True)
class ReviewTeam:
    key: str
    name: str
    members: tuple[str, ...]
    labels: tuple[str, ...]
    discord_role: str | int | None = None  # role name, or role ID


@dataclass(frozen=True)
class TeamMatch:
    team: ReviewTeam
    labels: tuple[str, ...]  # the team's labels found on the PR or its issues; () if none


def load_review_teams(path: Path) -> tuple[ReviewTeam, ...]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read {path}: {exc}") from exc
    return parse_review_teams(text)


def parse_review_teams(text: str) -> tuple[ReviewTeam, ...]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"review-teams.toml is not valid TOML: {exc}") from exc

    raw_teams = data.get("teams")
    if not isinstance(raw_teams, dict) or not raw_teams:
        raise ConfigError("review-teams.toml must define at least one [teams.<key>] table")
    return tuple(_parse_team(key, raw) for key, raw in raw_teams.items())


def _parse_team(key: str, raw: object) -> ReviewTeam:
    where = f"[teams.{key}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"{where} must be a table")
    unknown = set(raw) - TEAM_KEYS
    if unknown:
        raise ConfigError(f"{where} has unknown keys: {', '.join(sorted(unknown))}")

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"{where} needs a name")

    role = raw.get("discord_role")
    if isinstance(role, str):
        role = role.strip().removeprefix("@").strip()
    if role is not None and not (
        (isinstance(role, str) and role) or (type(role) is int and role > 0)
    ):
        raise ConfigError(f"{where} discord_role must be a role name or a role ID")

    def strings(field: str) -> tuple[str, ...]:
        values = raw.get(field, [])
        if not isinstance(values, list) or not all(
            isinstance(v, str) and v.strip() for v in values
        ):
            raise ConfigError(f"{where} {field} must be a list of non-empty strings")
        return tuple(v.strip() for v in values)

    members = tuple(m.removeprefix("@") for m in strings("members"))
    labels = strings("labels")
    if not labels:
        raise ConfigError(f"{where} needs at least one label")
    return ReviewTeam(key, name.strip(), members, labels, role)


def match_teams(teams: Sequence[ReviewTeam], labels: Iterable[str]) -> list[TeamMatch]:
    """The teams whose labels are on the PR, in config order (labels compare in any case).

    When no team's label is there, every team, with no labels.
    """
    found = {label.casefold() for label in labels}
    matches = []
    for team in teams:
        team_labels = tuple(label for label in team.labels if label.casefold() in found)
        if team_labels:
            matches.append(TeamMatch(team, team_labels))
    return matches or [TeamMatch(team, ()) for team in teams]


def reviewers_for(matches: Iterable[TeamMatch], author: str) -> list[str]:
    """Members of the matched teams, without the PR author (who cannot review their own PR)."""
    reviewers: dict[str, str] = {}
    for match in matches:
        for member in match.team.members:
            if member.casefold() != author.casefold():
                reviewers.setdefault(member.casefold(), member)
    return sorted(reviewers.values(), key=str.casefold)
