"""Milestone deadline reminders, 3 days and 1 day before each due date.

The scheduled loop and `/run deadlines` both call `run_check`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from discord.ext import commands, tasks

from team_bot import formatting
from team_bot.domain.deadlines import due_deadline_reminders, next_deadline
from team_bot.domain.iterations import Iteration, Milestone, build_iterations, release_for

if TYPE_CHECKING:
    from team_bot.bot import TeamBot

log = logging.getLogger(__name__)


class DeadlinesCog(commands.Cog):
    def __init__(self, bot: TeamBot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.check_deadlines.start()

    async def cog_unload(self) -> None:
        self.check_deadlines.cancel()

    async def _post(
        self, milestone: Milestone, days_left: int, iterations: list[Iteration]
    ) -> None:
        iteration = next((it for it in iterations if it.milestone.number == milestone.number), None)
        release = (
            release_for(iteration, iterations, self.bot.settings.releases) if iteration else None
        )
        message = formatting.deadline_message(
            milestone, days_left, release, iteration.number if iteration else None
        )
        await self.bot.send_to(
            self.bot.settings.reminders_channel_id, content=message, suppress_embeds=True
        )

    async def run_check(self, *, respect_hour: bool = True) -> list[str]:
        """Post every reminder that is due and record it. Returns what was posted.

        Raises if GitHub cannot be reached. A failed post is skipped (and retried next
        time) instead of stopping the others.
        """
        settings = self.bot.settings
        local_now = datetime.now(settings.timezone)
        if respect_hour and local_now.hour < settings.reminder_hour:
            return []  # the schedule posts during the day, not at midnight

        milestones = await self.bot.github.milestones()
        iterations = build_iterations(milestones)
        sent = self.bot.storage.sent_reminders()

        posted = []
        for milestone, kind, days_left in due_deadline_reminders(
            milestones, local_now.date(), sent
        ):
            try:
                await self._post(milestone, days_left, iterations)
            except Exception:
                log.exception("Could not post deadline reminder for %s", milestone.title)
                continue
            now = datetime.now(UTC)
            self.bot.storage.mark_reminder_sent(milestone.number, kind, now)
            if kind == "1d":
                # The 3-day window has passed; never send it after the 1-day one.
                self.bot.storage.mark_reminder_sent(milestone.number, "3d", now)
            posted.append(f"{milestone.title} ({kind} reminder)")
        return posted

    async def post_next(self) -> list[str]:
        """Post a reminder for the next deadline right now, outside the normal windows.

        Not recorded as sent, so the scheduled 3d and 1d reminders still go out.
        """
        milestones = await self.bot.github.milestones()
        today = datetime.now(self.bot.settings.timezone).date()
        upcoming = next_deadline(milestones, today)
        if upcoming is None:
            return []
        milestone, days_left = upcoming
        await self._post(milestone, days_left, build_iterations(milestones))
        return [f"{milestone.title} (due in {days_left} days)"]

    @tasks.loop(minutes=30)
    async def check_deadlines(self) -> None:
        try:
            await self.run_check()
        except Exception:
            # An uncaught error would stop the loop for good.
            log.exception("Deadline check failed; will retry")

    @check_deadlines.before_loop
    async def _wait_until_ready(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: TeamBot) -> None:
    await bot.add_cog(DeadlinesCog(bot))
