"""Which team reviews a pull request (issue #76).

Teams live in `review-teams.toml`: GitHub usernames, an optional Discord role, and the
labels and paths each team owns. A PR goes to every team whose labels are on it (or on an
issue it closes) or whose paths it changes. The same file generates `.github/CODEOWNERS`,
so GitHub also asks those people for a review.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from team_bot.config import ConfigError

TEAM_KEYS = {"name", "discord_role_id", "members", "labels", "paths"}


@dataclass(frozen=True)
class ReviewTeam:
    key: str
    name: str
    members: tuple[str, ...]
    labels: tuple[str, ...]
    paths: tuple[str, ...]
    discord_role_id: int | None = None


@dataclass(frozen=True)
class TeamMatch:
    team: ReviewTeam
    labels: tuple[str, ...]  # the team's labels found on the PR or its issues
    files: tuple[str, ...]  # the changed files under the team's paths


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

    role_id = raw.get("discord_role_id")
    if role_id is not None and (not isinstance(role_id, int) or role_id <= 0):
        raise ConfigError(f"{where} discord_role_id must be a positive number")

    def strings(field: str) -> tuple[str, ...]:
        values = raw.get(field, [])
        if not isinstance(values, list) or not all(
            isinstance(v, str) and v.strip() for v in values
        ):
            raise ConfigError(f"{where} {field} must be a list of non-empty strings")
        return tuple(v.strip() for v in values)

    members = tuple(m.removeprefix("@") for m in strings("members"))
    labels = strings("labels")
    paths = strings("paths")
    if not labels and not paths:
        raise ConfigError(f"{where} needs at least one label or path")
    for pattern in paths:
        if pattern.startswith(("/", "!")):
            raise ConfigError(f"{where} path {pattern!r} must be relative, without / or !")

    return ReviewTeam(key, name.strip(), members, labels, paths, role_id)


@cache
def _pattern_regex(pattern: str) -> re.Pattern[str]:
    """`dir/` matches everything under dir, `*` stays within a folder, `**` crosses them."""
    regex = ""
    for part in re.split(r"(\*\*/|\*\*|\*|\?)", pattern.rstrip("/")):
        if part == "**/":
            regex += "(?:.*/)?"
        elif part == "**":
            regex += ".*"
        elif part == "*":
            regex += "[^/]*"
        elif part == "?":
            regex += "[^/]"
        else:
            regex += re.escape(part)
    if pattern.endswith("/"):
        regex += "/.*"
    return re.compile(regex)


def path_matches(pattern: str, path: str) -> bool:
    return _pattern_regex(pattern).fullmatch(path) is not None


def match_teams(
    teams: Sequence[ReviewTeam], labels: Iterable[str], files: Iterable[str]
) -> list[TeamMatch]:
    """Every team the PR concerns, in config order. Labels compare case-insensitively."""
    found = {label.casefold() for label in labels}
    files = list(files)
    matches = []
    for team in teams:
        team_labels = tuple(label for label in team.labels if label.casefold() in found)
        team_files = tuple(f for f in files if any(path_matches(p, f) for p in team.paths))
        if team_labels or team_files:
            matches.append(TeamMatch(team, team_labels, team_files))
    return matches


def reviewers_for(matches: Iterable[TeamMatch], author: str) -> list[str]:
    """Members of the matched teams, without the PR author (who cannot review their own PR)."""
    reviewers: dict[str, str] = {}
    for match in matches:
        for member in match.team.members:
            if member.casefold() != author.casefold():
                reviewers.setdefault(member.casefold(), member)
    return sorted(reviewers.values(), key=str.casefold)


def codeowners_pattern(pattern: str) -> str:
    # CODEOWNERS patterns without a leading slash match at any depth; ours start at the root.
    return pattern if pattern.startswith("**/") else "/" + pattern


def render_codeowners(teams: Sequence[ReviewTeam]) -> str:
    lines = [
        "# Generated from discord-bots/team-bot/review-teams.toml (issue #76).",
        "# Do not edit by hand: change review-teams.toml, then run from discord-bots/team-bot",
        "#   python -m team_bot.codeowners",
        "#",
        "# When several lines match a file, the last one wins.",
    ]
    for team in teams:
        owners = " ".join(f"@{member}" for member in team.members)
        lines += ["", f"# {team.name}" + ("" if owners else " (no members listed yet)")]
        lines += [f"{codeowners_pattern(p)} {owners}".rstrip() for p in team.paths]
    return "\n".join(lines) + "\n"
