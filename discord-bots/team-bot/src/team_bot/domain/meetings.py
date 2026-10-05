"""Meetings: parsing user input and deciding when reminders are due."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

DAY_BEFORE = timedelta(days=1)
HOUR_BEFORE = timedelta(hours=1)


@dataclass(frozen=True)
class Meeting:
    id: int
    title: str
    starts_at: datetime  # aware, UTC
    link: str | None
    created_by: int
    created_at: datetime  # aware, UTC
    reminded_1d: bool = False
    reminded_1h: bool = False


class MeetingInputError(ValueError):
    pass


def parse_meeting_start(day: str, at: str, tz: ZoneInfo, now: datetime) -> datetime:
    """Parse "2026-10-14" and "18:30" in the team's timezone into an aware UTC datetime."""
    try:
        parsed_day = date.fromisoformat(day.strip())
    except ValueError as exc:
        raise MeetingInputError("Date must look like YYYY-MM-DD, for example 2026-10-14.") from exc

    hours, sep, minutes = at.strip().partition(":")
    try:
        if not sep:
            raise ValueError
        parsed_time = time(int(hours), int(minutes))
    except ValueError as exc:
        raise MeetingInputError("Time must look like HH:MM (24h), for example 18:30.") from exc

    local = datetime.combine(parsed_day, parsed_time, tzinfo=tz)
    starts_at = local.astimezone(UTC)
    if starts_at <= now:
        raise MeetingInputError("That time is already in the past.")
    return starts_at


def due_meeting_reminders(meetings: Iterable[Meeting], now: datetime) -> list[tuple[Meeting, str]]:
    """Return (meeting, kind) pairs to send now, where kind is "1d" or "1h".

    - "1h" fires in the last hour before the meeting.
    - "1d" fires in the day before the meeting, but only if the meeting was
      scheduled more than a day ahead (otherwise the announcement already did the job).
    A reminder whose window was missed (bot offline) is skipped, never sent late.
    """
    due = []
    for meeting in meetings:
        if meeting.starts_at <= now:
            continue
        time_left = meeting.starts_at - now
        if time_left <= HOUR_BEFORE:
            if not meeting.reminded_1h:
                due.append((meeting, "1h"))
        elif time_left <= DAY_BEFORE:
            scheduled_early = meeting.starts_at - meeting.created_at > DAY_BEFORE
            if scheduled_early and not meeting.reminded_1d:
                due.append((meeting, "1d"))
    return due
