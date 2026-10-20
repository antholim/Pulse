"""/run: trigger the scheduled jobs on demand.

Each subcommand calls the same method the schedule uses, so a manual run behaves exactly
like a scheduled one (same checks, same messages, same "already sent" records). The only
differences: deadline reminders ignore REMINDER_HOUR, the PR summary posts even when
no PR is waiting, and review routing with `pr` pings that PR's teams again.
`force: True` posts the next reminder even if it is not due yet.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, cast

import discord
from discord import app_commands
from discord.ext import commands

from team_bot import formatting

if TYPE_CHECKING:
    from team_bot.bot import TeamBot
    from team_bot.cogs.deadlines import DeadlinesCog
    from team_bot.cogs.meetings import MeetingsCog
    from team_bot.cogs.pr_summary import PRSummaryCog
    from team_bot.cogs.review_routing import ReviewRoutingCog

log = logging.getLogger(__name__)

# One manual run per job every 30 seconds per server, so nobody floods the channel.
COOLDOWN = app_commands.checks.cooldown(1, 30.0, key=lambda i: (i.guild_id, i.command.name))


class RunCog(commands.Cog):
    run = app_commands.Group(name="run", description="Run a scheduled job now")

    def __init__(self, bot: TeamBot) -> None:
        self.bot = bot

    async def _execute(
        self,
        interaction: discord.Interaction,
        job: str,
        action: Callable[[], Awaitable[list[str]]],
        force_hint: bool,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            posted = await action()
        except Exception as exc:
            log.exception("Manual run of %s failed", job)
            await interaction.followup.send(
                f"Could not run {job}: {type(exc).__name__}. Details are in the bot logs.",
                ephemeral=True,
            )
            return
        log.info("%s ran %s manually, posted %d", interaction.user, job, len(posted))
        await interaction.followup.send(
            formatting.run_result(job, posted, force_hint=force_hint), ephemeral=True
        )

    @run.command(name="deadlines", description="Post the milestone deadline reminders due now")
    @app_commands.describe(force="Post a reminder for the next deadline even if it is not due yet")
    @COOLDOWN
    async def deadlines(self, interaction: discord.Interaction, force: bool = False) -> None:
        cog = cast("DeadlinesCog", self.bot.get_cog("DeadlinesCog"))
        action = cog.post_next if force else lambda: cog.run_check(respect_hour=False)
        await self._execute(interaction, "deadline reminders", action, force_hint=not force)

    @run.command(name="meeting-reminders", description="Post the meeting reminders due now")
    @app_commands.describe(force="Remind everyone of the next meeting even if it is not due yet")
    @COOLDOWN
    async def meeting_reminders(
        self, interaction: discord.Interaction, force: bool = False
    ) -> None:
        cog = cast("MeetingsCog", self.bot.get_cog("MeetingsCog"))
        action = cog.post_next if force else cog.run_check
        await self._execute(interaction, "meeting reminders", action, force_hint=not force)

    @run.command(name="pr-summary", description="Post the open PR summary to the channel now")
    @COOLDOWN
    async def pr_summary(self, interaction: discord.Interaction) -> None:
        cog = cast("PRSummaryCog", self.bot.get_cog("PRSummaryCog"))
        await self._execute(
            interaction,
            "the PR summary",
            lambda: cog.post_summary(skip_if_empty=False),
            force_hint=False,
        )

    @run.command(
        name="review-routing", description="Ping the teams of PRs that are ready for review"
    )
    @app_commands.describe(pr="Ping the teams of this open PR now, even if they were pinged")
    @COOLDOWN
    async def review_routing(self, interaction: discord.Interaction, pr: int | None = None) -> None:
        cog = cast("ReviewRoutingCog", self.bot.get_cog("ReviewRoutingCog"))
        action = cog.run_check if pr is None else lambda: cog.route_now(pr)
        await self._execute(interaction, "review routing", action, force_hint=False)


async def setup(bot: TeamBot) -> None:
    await bot.add_cog(RunCog(bot))
