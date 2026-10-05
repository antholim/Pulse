from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from team_bot.bot import TeamBot


class General(commands.Cog):
    def __init__(self, bot: TeamBot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Check that the bot is online")
    async def ping(self, interaction: discord.Interaction) -> None:
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"Pong ({latency_ms} ms)", ephemeral=True)


async def setup(bot: TeamBot) -> None:
    await bot.add_cog(General(bot))
