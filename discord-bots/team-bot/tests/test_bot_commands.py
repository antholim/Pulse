"""Load every command module without connecting to Discord, and check the command tree.

This catches broken decorators, bad option types and missing setup() functions.
"""

from team_bot.bot import EXTENSIONS, TeamBot
from team_bot.config import Settings

from tests_support import FakeGitHub

ENV = {
    "DISCORD_TOKEN": "x",
    "DISCORD_GUILD_ID": "1",
    "GITHUB_REPO": "antholim/Pulse",
    "REMINDERS_CHANNEL_ID": "2",
    "GITHUB_TOKEN": "t",
}


async def test_all_commands_register(storage):
    bot = TeamBot(Settings.from_env(ENV), storage, FakeGitHub())
    for extension in EXTENSIONS:
        await bot.load_extension(extension)
    try:
        names = {command.qualified_name for command in bot.tree.walk_commands()}
        assert names >= {
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
    finally:
        for extension in EXTENSIONS:
            await bot.unload_extension(extension)
        await bot.http.close()
