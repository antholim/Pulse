"""/ping and /help."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from team_bot import formatting
from team_bot.formatting import CommandHelp

if TYPE_CHECKING:
    from team_bot.bot import TeamBot


def collect_help(tree: app_commands.CommandTree) -> list[CommandHelp]:
    """Describe every registered slash command, read straight from the command tree.

    Built at call time, so /help always matches the commands the bot really has.
    Groups such as /meeting are skipped; their subcommands are listed instead.
    """
    entries = []
    for command in tree.walk_commands():
        if not isinstance(command, app_commands.Command):
            continue
        owner = command.binding
        if owner is None and command.parent is not None:
            owner = command.parent.binding
        entries.append(
            CommandHelp(
                name=command.qualified_name,
                description=command.description,
                params=tuple((p.display_name, p.required) for p in command.parameters),
                cog=type(owner).__name__ if owner is not None else "",
            )
        )
    return entries


class General(commands.Cog):
    def __init__(self, bot: TeamBot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Check that the bot is online")
    async def ping(self, interaction: discord.Interaction) -> None:
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"Pong ({latency_ms} ms)", ephemeral=True)

    @app_commands.command(name="help", description="List every bot command")
    async def help_command(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="Team bot commands",
            description=(
                "Type `/` and pick a command to fill in its options. "
                "Options in [brackets] are optional."
            ),
            colour=discord.Colour.blurple(),
        )
        for title, text in formatting.help_sections(collect_help(self.bot.tree)):
            embed.add_field(name=title, value=text, inline=False)
        embed.add_field(
            name="Automatic posts",
            value=formatting.automatic_posts(self.bot.settings.pr_summary_time),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: TeamBot) -> None:
    await bot.add_cog(General(bot))
