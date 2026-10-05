"""Decide which milestone deadline reminders are due."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from datetime import date

from team_bot.domain.iterations import Milestone

# kind -> days left before the due date at which the reminder opens
REMINDER_KINDS = {"3d": 3, "1d": 1}


def due_deadline_reminders(
    milestones: Iterable[Milestone],
    today: date,
    already_sent: Collection[tuple[int, str]],
) -> list[tuple[Milestone, str, int]]:
    """Return (milestone, kind, days_left) for reminders to post today.

    The "3d" reminder opens 3 days before the due date and the "1d" reminder
    1 day before. If the bot was offline when the 3-day window opened, it still
    sends it on day 2. When both are open (bot offline for days), only "1d" is sent
    and the caller should record "3d" as sent too.
    """
    due = []
    for milestone in milestones:
        if milestone.state != "open" or milestone.due_date is None:
            continue
        days_left = (milestone.due_date - today).days
        if days_left < 0:
            continue
        if days_left <= REMINDER_KINDS["1d"]:
            if (milestone.number, "1d") not in already_sent:
                due.append((milestone, "1d", days_left))
        elif days_left <= REMINDER_KINDS["3d"] and (milestone.number, "3d") not in already_sent:
            due.append((milestone, "3d", days_left))
    return due


def next_deadline(milestones: Iterable[Milestone], today: date) -> tuple[Milestone, int] | None:
    """The open milestone due soonest (today or later), with its days left.

    Used by `/run deadlines force:True` to post a reminder outside the normal windows.
    """
    upcoming = [
        (milestone, (milestone.due_date - today).days)
        for milestone in milestones
        if milestone.state == "open"
        and milestone.due_date is not None
        and milestone.due_date >= today
    ]
    if not upcoming:
        return None
    return min(upcoming, key=lambda pair: (pair[1], pair[0].number))
