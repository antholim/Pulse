"""Settings read from environment variables (and a local .env file in development)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_RELEASES = "Release 1=4,Release 2=8,Final Release=13"


class ConfigError(ValueError):
    """Raised when a required setting is missing or malformed."""


@dataclass(frozen=True)
class GitHubAuth:
    """Either a token, or the three values of a GitHub App installation."""

    token: str | None = None
    app_id: str | None = None
    installation_id: int | None = None
    private_key: str | None = None

    @property
    def uses_app(self) -> bool:
        return self.token is None


@dataclass(frozen=True)
class Release:
    name: str
    last_iteration: int


@dataclass(frozen=True)
class Settings:
    discord_token: str
    guild_id: int
    github_repo: str
    github_auth: GitHubAuth
    reminders_channel_id: int
    pr_summary_channel_id: int
    pr_summary_time: time | None
    pr_summary_role_id: int | None
    timezone: ZoneInfo
    reminder_hour: int
    db_path: Path
    releases: tuple[Release, ...]

    @property
    def repo_owner(self) -> str:
        return self.github_repo.split("/", 1)[0]

    @property
    def repo_name(self) -> str:
        return self.github_repo.split("/", 1)[1]

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        missing: list[str] = []

        def required(name: str) -> str:
            value = env.get(name, "").strip()
            if not value:
                missing.append(name)
            return value

        def optional(name: str, default: str = "") -> str:
            return env.get(name, default).strip()

        discord_token = required("DISCORD_TOKEN")
        guild_id = required("DISCORD_GUILD_ID")
        github_repo = required("GITHUB_REPO")
        reminders_channel = required("REMINDERS_CHANNEL_ID")
        github_auth = _github_auth(env, missing)

        if missing:
            raise ConfigError("Missing environment variables: " + ", ".join(missing))

        if github_repo.count("/") != 1:
            raise ConfigError("GITHUB_REPO must look like owner/name, got " + repr(github_repo))

        tz_name = optional("TIMEZONE", "America/Toronto")
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ConfigError(f"Unknown TIMEZONE {tz_name!r}") from exc

        summary_time_raw = optional("PR_SUMMARY_TIME", "21:00")
        pr_summary_time = _parse_time(summary_time_raw, tz) if summary_time_raw else None

        reminder_hour = _to_int("REMINDER_HOUR", optional("REMINDER_HOUR", "9"))
        if not 0 <= reminder_hour <= 23:
            raise ConfigError("REMINDER_HOUR must be between 0 and 23")

        role = optional("PR_SUMMARY_ROLE_ID")
        summary_channel = optional("PR_SUMMARY_CHANNEL_ID") or reminders_channel

        return cls(
            discord_token=discord_token,
            guild_id=_to_int("DISCORD_GUILD_ID", guild_id),
            github_repo=github_repo,
            github_auth=github_auth,
            reminders_channel_id=_to_int("REMINDERS_CHANNEL_ID", reminders_channel),
            pr_summary_channel_id=_to_int("PR_SUMMARY_CHANNEL_ID", summary_channel),
            pr_summary_time=pr_summary_time,
            pr_summary_role_id=_to_int("PR_SUMMARY_ROLE_ID", role) if role else None,
            timezone=tz,
            reminder_hour=reminder_hour,
            db_path=Path(optional("DB_PATH", "data/team-bot.db")),
            releases=parse_releases(optional("RELEASES", DEFAULT_RELEASES)),
        )


def _github_auth(env: Mapping[str, str], missing: list[str]) -> GitHubAuth:
    token = env.get("GITHUB_TOKEN", "").strip()
    if token:
        return GitHubAuth(token=token)

    app_id = env.get("GITHUB_APP_ID", "").strip()
    installation_id = env.get("GITHUB_INSTALLATION_ID", "").strip()
    key = env.get("GITHUB_PRIVATE_KEY", "").strip()
    key_path = env.get("GITHUB_PRIVATE_KEY_PATH", "").strip()

    if not (app_id or installation_id or key or key_path):
        missing.append(
            "GITHUB_TOKEN (or GITHUB_APP_ID + GITHUB_INSTALLATION_ID + GITHUB_PRIVATE_KEY)"
        )
        return GitHubAuth()

    if not app_id:
        missing.append("GITHUB_APP_ID")
    if not installation_id:
        missing.append("GITHUB_INSTALLATION_ID")
    if not key and key_path:
        try:
            key = Path(key_path).read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"Cannot read GITHUB_PRIVATE_KEY_PATH {key_path!r}: {exc}") from exc
    if not key:
        missing.append("GITHUB_PRIVATE_KEY or GITHUB_PRIVATE_KEY_PATH")
    if missing:
        return GitHubAuth()

    # Keys pasted into a single-line env var usually have literal "\n" sequences.
    key = key.replace("\\n", "\n")
    return GitHubAuth(
        app_id=app_id,
        installation_id=_to_int("GITHUB_INSTALLATION_ID", installation_id),
        private_key=key,
    )


def parse_releases(raw: str) -> tuple[Release, ...]:
    """Parse "Release 1=4,Release 2=8" into releases sorted by their last iteration."""
    releases = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        name, sep, last = part.rpartition("=")
        if not sep or not name.strip():
            raise ConfigError(f"RELEASES entry {part!r} must look like 'Release 1=4'")
        releases.append(Release(name.strip(), _to_int("RELEASES", last.strip())))
    if not releases:
        raise ConfigError("RELEASES must list at least one release")
    return tuple(sorted(releases, key=lambda r: r.last_iteration))


def _parse_time(raw: str, tz: ZoneInfo) -> time:
    hours, sep, minutes = raw.partition(":")
    try:
        if not sep:
            raise ValueError
        return time(int(hours), int(minutes), tzinfo=tz)
    except ValueError as exc:
        raise ConfigError(f"PR_SUMMARY_TIME must look like HH:MM, got {raw!r}") from exc


def _to_int(name: str, raw: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc
