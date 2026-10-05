from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest

from team_bot.domain.meetings import (
    Meeting,
    MeetingInputError,
    due_meeting_reminders,
    parse_meeting_start,
)

from conftest import utc

TORONTO = ZoneInfo("America/Toronto")
NOW = utc("2026-10-10T12:00:00")


def test_parse_local_time_to_utc():
    # 18:30 in Toronto during daylight time (UTC-4) is 22:30 UTC.
    assert parse_meeting_start("2026-10-14", "18:30", TORONTO, NOW) == utc("2026-10-14T22:30:00")


def test_parse_handles_winter_time():
    # After the November clock change Toronto is UTC-5.
    assert parse_meeting_start("2026-11-10", "18:30", TORONTO, NOW) == utc("2026-11-10T23:30:00")


@pytest.mark.parametrize(
    ("day", "at", "match"),
    [
        ("14/10/2026", "18:30", "YYYY-MM-DD"),
        ("2026-10-14", "6pm", "HH:MM"),
        ("2026-10-14", "25:00", "HH:MM"),
        ("2026-10-01", "10:00", "past"),
    ],
)
def test_parse_rejects_bad_input(day, at, match):
    with pytest.raises(MeetingInputError, match=match):
        parse_meeting_start(day, at, TORONTO, NOW)


def meeting(starts_in, created_before_start=timedelta(days=3), **flags):
    starts_at = NOW + starts_in
    return Meeting(1, "Planning", starts_at, None, 99, starts_at - created_before_start, **flags)


@pytest.mark.parametrize(
    ("starts_in", "expected"),
    [
        (timedelta(days=2), []),
        (timedelta(hours=23), ["1d"]),
        (timedelta(hours=2), ["1d"]),
        (timedelta(minutes=59), ["1h"]),
        (timedelta(minutes=-5), []),  # already started
    ],
)
def test_reminder_windows(starts_in, expected):
    assert [kind for _, kind in due_meeting_reminders([meeting(starts_in)], NOW)] == expected


def test_no_day_reminder_for_meetings_scheduled_less_than_a_day_ahead():
    late = meeting(timedelta(hours=5), created_before_start=timedelta(hours=6))
    assert due_meeting_reminders([late], NOW) == []


def test_sent_reminders_are_not_repeated():
    assert due_meeting_reminders([meeting(timedelta(hours=5), reminded_1d=True)], NOW) == []
    assert due_meeting_reminders([meeting(timedelta(minutes=30), reminded_1h=True)], NOW) == []


def test_missed_day_reminder_is_not_sent_in_the_last_hour():
    # Only the 1h reminder fires, even if the 1d one was never sent.
    due = due_meeting_reminders([meeting(timedelta(minutes=30))], NOW)
    assert [kind for _, kind in due] == ["1h"]
