"""Daily summary of open pull requests (ported from last year's JS bot), plus /prs.

The scheduled loop and `/run pr-summary` both call `post_summary`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks

from team_bot import formatting

if TYPE_CHECKING:
    from team_bot.bot import TeamBot

log = logging.getLogger(__name__)


class PRSummaryCog(commands.Cog):
    def __init__(self, bot: TeamBot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        summary_time = self.bot.settings.pr_summary_time
        if summary_time is not None:
            self.daily_summary.change_interval(time=summary_time)
            self.daily_summary.start()

    async def cog_unload(self) -> None:
        self.daily_summary.cancel()

    async def _build_embed(self) -> tuple[discord.Embed, int]:
        prs = await self.bot.github.open_pull_requests()
        title, description = formatting.pr_summary(prs, datetime.now(UTC))
        ready = sum(1 for pr in prs if not pr.draft)
        colour = discord.Colour.orange() if ready else discord.Colour.green()
        return discord.Embed(title=title, description=description, colour=colour), ready

    async def post_summary(self, *, skip_if_empty: bool) -> list[str]:
        """Post the open PR summary to the summary channel. Returns what was posted.

        The daily schedule skips the post when no PR is waiting; a manual run always posts.
        """
        embed, ready = await self._build_embed()
        if ready == 0 and skip_if_empty:
            return []
        role_id = self.bot.settings.pr_summary_role_id
        content = f"<@&{role_id}>" if role_id and ready else None
        await self.bot.send_to(
            self.bot.settings.pr_summary_channel_id, content=content, embed=embed
        )
        return [embed.title or "Open PR summary"]

    @app_commands.command(name="prs", description="Show open pull requests (only you see it)")
    async def prs(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        embed, _ = await self._build_embed()
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tasks.loop(hours=24)  # replaced by the PR_SUMMARY_TIME schedule in cog_load
    async def daily_summary(self) -> None:
        try:
            await self.post_summary(skip_if_empty=True)
        except Exception:
            # An uncaught error would stop the loop for good.
            log.exception("Could not post the daily PR summary")

    @daily_summary.before_loop
    async def _wait_until_ready(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: TeamBot) -> None:
    await bot.add_cog(PRSummaryCog(bot))
