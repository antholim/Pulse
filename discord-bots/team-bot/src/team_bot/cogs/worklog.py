"""/log, /unlog and /contributions."""

from __future__ import annotations

import io
import logging
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Literal

import discord
from discord import app_commands
from discord.ext import commands

from team_bot import formatting
from team_bot.domain.iterations import Iteration, build_iterations, iteration_for, release_for
from team_bot.domain.worklog import MAX_HOURS, MIN_HOURS, summarize, validate_entry

if TYPE_CHECKING:
    from team_bot.bot import TeamBot

log = logging.getLogger(__name__)


class WorkLogCog(commands.Cog):
    def __init__(self, bot: TeamBot) -> None:
        self.bot = bot

    def _today(self) -> date:
        return datetime.now(self.bot.settings.timezone).date()

    async def _iterations(self) -> list[Iteration]:
        try:
            return build_iterations(await self.bot.github.milestones())
        except Exception:
            log.exception("Could not load milestones from GitHub")
            return []

    @app_commands.command(name="log", description="Log work you did on the project")
    @app_commands.describe(
        description="What you did, for example 'Reviewed CSV import PR'",
        hours="Time spent in hours, for example 1.5",
        issue="Issue or PR number this work was for (optional)",
        day="Date as YYYY-MM-DD (defaults to today)",
    )
    async def log_work(
        self,
        interaction: discord.Interaction,
        description: app_commands.Range[str, 1, 500],
        hours: app_commands.Range[float, MIN_HOURS, MAX_HOURS],
        issue: app_commands.Range[int, 1] | None = None,
        day: str | None = None,
    ) -> None:
        today = self._today()
        try:
            work_date = date.fromisoformat(day.strip()) if day else today
        except ValueError:
            await interaction.response.send_message(
                "Date must look like YYYY-MM-DD, for example 2026-10-14.", ephemeral=True
            )
            return

        error = validate_entry(hours, work_date, today, description)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        entry = self.bot.storage.add_work_log(
            discord_id=interaction.user.id,
            display_name=interaction.user.display_name,
            work_date=work_date,
            description=description,
            hours=hours,
            reference=issue,
            now=datetime.now(UTC),
        )
        iteration = iteration_for(work_date, await self._iterations())
        await interaction.followup.send(
            formatting.log_confirmation(entry, self.bot.settings.github_repo, iteration),
            ephemeral=True,
            suppress_embeds=True,
        )

    @app_commands.command(name="unlog", description="Delete one of your own work log entries")
    @app_commands.describe(entry="Entry number shown when you logged it")
    async def unlog(self, interaction: discord.Interaction, entry: int) -> None:
        deleted = self.bot.storage.delete_work_log(entry, interaction.user.id)
        message = (
            f"Deleted entry `#{entry}`." if deleted else f"No entry `#{entry}` of yours was found."
        )
        await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(
        name="contributions", description="Hours logged per member for an iteration or release"
    )
    @app_commands.describe(
        period="Current iteration (default), current release, or everything",
        member="Only show this member",
        export="Also attach a markdown file for the wiki",
    )
    async def contributions(
        self,
        interaction: discord.Interaction,
        period: Literal["iteration", "release", "all"] = "iteration",
        member: discord.User | None = None,
        export: bool = False,
    ) -> None:
        await interaction.response.defer()
        settings = self.bot.settings
        today = self._today()
        iterations = await self._iterations()
        current = iteration_for(today, iterations)

        if period == "all":
            title = "Contributions: all time"
            start = end = None
        elif current is None:
            await interaction.followup.send(
                "Today is not inside any 'Iteration N' milestone on GitHub, so there is no "
                "current iteration. Try `period: all`."
            )
            return
        elif period == "release":
            release = release_for(current, iterations, settings.releases)
            if release is None:
                await interaction.followup.send(
                    f"{current.title} is not part of any release in the RELEASES setting."
                )
                return
            title = f"Contributions: {release.name}"
            start, end = release.start, release.end
        else:
            title = f"Contributions: {current.title}"
            start, end = current.start, current.end

        logs = self.bot.storage.list_work_logs(start, end, member.id if member else None)
        if member:
            title += f" · {member.display_name}"
        shown_start = start or (logs[0].work_date if logs else today)
        shown_end = end or (logs[-1].work_date if logs else today)

        embed = discord.Embed(
            title=title,
            description=formatting.contributions_description(
                summarize(logs), shown_start, shown_end, settings.github_repo
            ),
            colour=discord.Colour.blurple(),
        )
        kwargs: dict = {"embed": embed}
        if export:
            markdown = formatting.contributions_markdown(logs, iterations, settings.github_repo)
            kwargs["file"] = discord.File(
                io.BytesIO(markdown.encode("utf-8")), filename="contributions.md"
            )
        await interaction.followup.send(**kwargs)


async def setup(bot: TeamBot) -> None:
    await bot.add_cog(WorkLogCog(bot))
