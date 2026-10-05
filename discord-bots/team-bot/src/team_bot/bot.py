"""The Discord client: loads the command modules and syncs slash commands to the server."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from team_bot.config import Settings
from team_bot.services.github import GitHubReader
from team_bot.services.storage import Storage

log = logging.getLogger(__name__)

EXTENSIONS = (
    "team_bot.cogs.general",
    "team_bot.cogs.worklog",
    "team_bot.cogs.meetings",
    "team_bot.cogs.deadlines",
    "team_bot.cogs.pr_summary",
    "team_bot.cogs.run",  # after the cogs whose jobs it triggers
)


class TeamBot(commands.Bot):
    def __init__(self, settings: Settings, storage: Storage, github: GitHubReader) -> None:
        super().__init__(
            # Slash commands only; no privileged intents (message content, members) needed.
            command_prefix=commands.when_mentioned,
            intents=discord.Intents.default(),
            # Never let a message ping @everyone or @here.
            allowed_mentions=discord.AllowedMentions(everyone=False, users=True, roles=True),
        )
        self.settings = settings
        self.storage = storage
        self.github = github
        self.tree.on_error = self.on_app_command_error

    async def setup_hook(self) -> None:
        for extension in EXTENSIONS:
            await self.load_extension(extension)
        # Syncing to one server makes command changes show up immediately.
        guild = discord.Object(id=self.settings.guild_id)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        log.info("Synced %d slash commands to guild %s", len(synced), self.settings.guild_id)

    async def on_ready(self) -> None:
        log.info("Logged in as %s", self.user)

    async def send_to(self, channel_id: int, **kwargs) -> discord.Message:
        channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            raise RuntimeError(f"Channel {channel_id} cannot receive messages")
        return await channel.send(**kwargs)

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        log.exception("Command %s failed", interaction.command, exc_info=error)
        message = "Something went wrong running that command. The error was logged."
        if isinstance(error, app_commands.CheckFailure):
            message = str(error) or "You cannot use this command."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def close(self) -> None:
        await super().close()
        self.storage.close()
