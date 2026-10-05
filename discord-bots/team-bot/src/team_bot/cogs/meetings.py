"""/meeting schedule | list | cancel, plus reminders 1 day and 1 hour before."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks

from team_bot import formatting
from team_bot.domain.meetings import (
    Meeting,
    MeetingInputError,
    due_meeting_reminders,
    parse_meeting_start,
)

if TYPE_CHECKING:
    from team_bot.bot import TeamBot

log = logging.getLogger(__name__)


class MeetingsCog(commands.Cog):
    meeting = app_commands.Group(name="meeting", description="Schedule team meetings")

    def __init__(self, bot: TeamBot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.reminder_loop.start()

    async def cog_unload(self) -> None:
        self.reminder_loop.cancel()

    @meeting.command(name="schedule", description="Schedule a meeting with automatic reminders")
    @app_commands.describe(
        title="What the meeting is, for example 'Sprint planning'",
        date="Date as YYYY-MM-DD",
        time="Start time as HH:MM (24h, team timezone)",
        link="Call link or room (optional)",
    )
    async def schedule(
        self,
        interaction: discord.Interaction,
        title: app_commands.Range[str, 1, 100],
        date: str,
        time: str,
        link: app_commands.Range[str, 1, 300] | None = None,
    ) -> None:
        now = datetime.now(UTC)
        try:
            starts_at = parse_meeting_start(date, time, self.bot.settings.timezone, now)
        except MeetingInputError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        meeting = self.bot.storage.add_meeting(title, starts_at, link, interaction.user.id, now)
        await interaction.response.send_message(
            f"📅 {interaction.user.mention} scheduled a meeting\n"
            f"{formatting.meeting_line(meeting)}\n"
            "Reminders will be posted 1 day and 1 hour before.",
            suppress_embeds=True,
        )

    @meeting.command(name="list", description="Show upcoming meetings")
    async def list_meetings(self, interaction: discord.Interaction) -> None:
        upcoming = self.bot.storage.upcoming_meetings(datetime.now(UTC))
        if not upcoming:
            await interaction.response.send_message("No upcoming meetings.", ephemeral=True)
            return
        lines = [formatting.meeting_line(m) for m in upcoming[:15]]
        await interaction.response.send_message(
            "**Upcoming meetings**\n" + "\n".join(lines), ephemeral=True, suppress_embeds=True
        )

    @meeting.command(name="cancel", description="Cancel a meeting you scheduled")
    @app_commands.describe(meeting_id="Meeting number from /meeting list")
    async def cancel(self, interaction: discord.Interaction, meeting_id: int) -> None:
        meeting = self.bot.storage.get_meeting(meeting_id)
        if meeting is None:
            await interaction.response.send_message(f"No meeting `#{meeting_id}`.", ephemeral=True)
            return
        perms = getattr(interaction.user, "guild_permissions", None)
        is_admin = bool(perms and perms.manage_guild)
        if meeting.created_by != interaction.user.id and not is_admin:
            await interaction.response.send_message(
                "Only the person who scheduled it (or a server manager) can cancel it.",
                ephemeral=True,
            )
            return
        self.bot.storage.cancel_meeting(meeting_id)
        await interaction.response.send_message(
            f"❌ {interaction.user.mention} cancelled **{meeting.title}** "
            f"({formatting.discord_time(meeting.starts_at)})."
        )

    @tasks.loop(minutes=1)
    async def reminder_loop(self) -> None:
        try:
            await self.run_check()
        except Exception:
            # An uncaught error would stop the loop for good.
            log.exception("Meeting reminder check failed; will retry")

    async def _post(self, meeting: Meeting) -> None:
        await self.bot.send_to(
            self.bot.settings.reminders_channel_id,
            content=formatting.meeting_reminder(meeting),
            suppress_embeds=True,
        )

    async def run_check(self) -> list[str]:
        """Post every meeting reminder that is due and record it. Returns what was posted.

        The scheduled loop and `/run meeting-reminders` both call this.
        """
        now = datetime.now(UTC)
        posted = []
        for meeting, kind in due_meeting_reminders(self.bot.storage.upcoming_meetings(now), now):
            try:
                await self._post(meeting)
            except Exception:
                # Not marked as sent, so it is retried on the next tick.
                log.exception("Could not post %s reminder for meeting %s", kind, meeting.id)
                continue
            self.bot.storage.mark_meeting_reminded(meeting.id, kind)
            posted.append(f"{meeting.title} ({kind} reminder)")
        return posted

    async def post_next(self) -> list[str]:
        """Remind everyone of the next meeting right now. Not recorded as sent."""
        upcoming = self.bot.storage.upcoming_meetings(datetime.now(UTC))
        if not upcoming:
            return []
        await self._post(upcoming[0])
        return [upcoming[0].title]

    @reminder_loop.before_loop
    async def _wait_until_ready(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: TeamBot) -> None:
    await bot.add_cog(MeetingsCog(bot))
