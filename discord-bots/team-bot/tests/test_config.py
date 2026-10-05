from datetime import time

import pytest

from team_bot.config import ConfigError, Release, Settings, parse_releases

BASE = {
    "DISCORD_TOKEN": "discord-token",
    "DISCORD_GUILD_ID": "111",
    "GITHUB_REPO": "antholim/Pulse",
    "REMINDERS_CHANNEL_ID": "222",
    "GITHUB_TOKEN": "gh-token",
}


def test_defaults_with_token_auth():
    settings = Settings.from_env(BASE)
    assert settings.guild_id == 111
    assert settings.repo_owner == "antholim"
    assert settings.repo_name == "Pulse"
    assert settings.github_auth.token == "gh-token"
    assert not settings.github_auth.uses_app
    assert settings.pr_summary_channel_id == 222  # falls back to the reminders channel
    assert settings.pr_summary_time == time(21, 0, tzinfo=settings.timezone)
    assert settings.timezone.key == "America/Toronto"
    assert settings.reminder_hour == 9
    assert settings.releases[0] == Release("Release 1", 4)


def test_missing_values_are_all_reported():
    with pytest.raises(ConfigError) as err:
        Settings.from_env({"DISCORD_TOKEN": "x"})
    message = str(err.value)
    for name in ("DISCORD_GUILD_ID", "GITHUB_REPO", "REMINDERS_CHANNEL_ID", "GITHUB_TOKEN"):
        assert name in message


def test_github_app_auth_from_key_value():
    env = {k: v for k, v in BASE.items() if k != "GITHUB_TOKEN"}
    env |= {
        "GITHUB_APP_ID": "42",
        "GITHUB_INSTALLATION_ID": "7",
        "GITHUB_PRIVATE_KEY": "-----BEGIN-----\\nabc\\n-----END-----",
    }
    auth = Settings.from_env(env).github_auth
    assert auth.uses_app
    assert auth.installation_id == 7
    assert auth.private_key == "-----BEGIN-----\nabc\n-----END-----"


def test_github_app_auth_from_key_file(tmp_path):
    key_file = tmp_path / "app.pem"
    key_file.write_text("KEY", encoding="utf-8")
    env = {k: v for k, v in BASE.items() if k != "GITHUB_TOKEN"}
    env |= {
        "GITHUB_APP_ID": "42",
        "GITHUB_INSTALLATION_ID": "7",
        "GITHUB_PRIVATE_KEY_PATH": str(key_file),
    }
    assert Settings.from_env(env).github_auth.private_key == "KEY"


def test_partial_github_app_config_is_rejected():
    env = {k: v for k, v in BASE.items() if k != "GITHUB_TOKEN"}
    env |= {"GITHUB_APP_ID": "42"}
    with pytest.raises(ConfigError, match="GITHUB_INSTALLATION_ID"):
        Settings.from_env(env)


@pytest.mark.parametrize(
    ("key", "value", "match"),
    [
        ("DISCORD_GUILD_ID", "abc", "DISCORD_GUILD_ID"),
        ("GITHUB_REPO", "no-slash", "owner/name"),
        ("TIMEZONE", "Mars/Olympus", "TIMEZONE"),
        ("PR_SUMMARY_TIME", "9pm", "HH:MM"),
        ("REMINDER_HOUR", "25", "REMINDER_HOUR"),
    ],
)
def test_bad_values(key, value, match):
    with pytest.raises(ConfigError, match=match):
        Settings.from_env(BASE | {key: value})


def test_empty_summary_time_disables_summary():
    assert Settings.from_env(BASE | {"PR_SUMMARY_TIME": ""}).pr_summary_time is None


def test_parse_releases_sorts_and_validates():
    assert parse_releases("B=8, A=4") == (Release("A", 4), Release("B", 8))
    with pytest.raises(ConfigError):
        parse_releases("nonsense")
    with pytest.raises(ConfigError):
        parse_releases(" , ")
