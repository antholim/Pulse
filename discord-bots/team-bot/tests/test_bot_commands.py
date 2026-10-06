"""Load every command module without connecting to Discord, and check the command tree.

This catches broken decorators, bad option types and missing setup() functions,
and checks that /help covers every command.
"""

import pytest

from team_bot import formatting
from team_bot.bot import EXTENSIONS, TeamBot
from team_bot.cogs.general import collect_help
from team_bot.config import Settings

from tests_support import FakeGitHub

ENV = {
    "DISCORD_TOKEN": "x",
    "DISCORD_GUILD_ID": "1",
    "GITHUB_REPO": "antholim/Pulse",
    "REMINDERS_CHANNEL_ID": "2",
    "GITHUB_TOKEN": "t",
}


@pytest.fixture
async def bot(storage):
    bot = TeamBot(Settings.from_env(ENV), storage, FakeGitHub())
    for extension in EXTENSIONS:
        await bot.load_extension(extension)
    yield bot
    for extension in EXTENSIONS:
        await bot.unload_extension(extension)
    await bot.http.close()


async def test_all_commands_register(bot):
    names = {command.qualified_name for command in bot.tree.walk_commands()}
    assert names >= {
        "help",
        "ping",
        "log",
        "unlog",
        "contributions",
        "prs",
        "meeting",
        "meeting schedule",
        "meeting list",
        "meeting cancel",
        "run",
        "run deadlines",
        "run meeting-reminders",
        "run pr-summary",
    }
    log_command = bot.tree.get_command("log")
    params = {p.name: p for p in log_command.parameters}
    assert params["hours"].min_value == 0.25 and params["hours"].max_value == 24
    assert not params["issue"].required
    contributions = bot.tree.get_command("contributions")
    period = next(p for p in contributions.parameters if p.name == "period")
    assert [c.value for c in period.choices] == ["iteration", "release", "all"]


async def test_help_lists_every_command_in_a_named_section(bot):
    entries = collect_help(bot.tree)
    names = {entry.name for entry in entries}
    leaf_commands = {
        c.qualified_name for c in bot.tree.walk_commands() if not hasattr(c, "commands")
    }
    assert names == leaf_commands  # nothing missing; groups like /meeting are not listed
    assert "help" in names and "meeting schedule" in names

    for entry in entries:
        assert entry.description, f"/{entry.name} needs a description for /help"
        assert entry.cog in formatting.HELP_SECTIONS, f"/{entry.name} has no /help section"

    by_name = {entry.name: entry for entry in entries}
    assert by_name["meeting schedule"].cog == "MeetingsCog"  # subcommands find their cog
    assert formatting.command_usage(by_name["log"]) == "/log description hours [issue] [day]"

    sections = formatting.help_sections(entries)
    assert [title for title, _ in sections] == list(formatting.HELP_SECTIONS.values())
    assert all(len(text) <= formatting.DISCORD_FIELD_LIMIT for _, text in sections)
