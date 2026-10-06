from datetime import date

import pytest

from team_bot.domain.deadlines import due_deadline_reminders, next_deadline

from conftest import make_milestone

MILESTONE = make_milestone(2, "2026-10-20")


def kinds(today, sent=(), milestones=(MILESTONE,)):
    return [
        (m.number, kind, days)
        for m, kind, days in due_deadline_reminders(milestones, today, set(sent))
    ]


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 10, 16), []),  # 4 days left
        (date(2026, 10, 17), [(2, "3d", 3)]),
        (date(2026, 10, 18), [(2, "3d", 2)]),  # catch-up if the bot was offline
        (date(2026, 10, 19), [(2, "1d", 1)]),
        (date(2026, 10, 20), [(2, "1d", 0)]),  # due today, still not sent
        (date(2026, 10, 21), []),  # overdue
    ],
)
def test_reminder_windows(today, expected):
    assert kinds(today) == expected


def test_sent_reminders_are_not_repeated():
    assert kinds(date(2026, 10, 17), sent={(2, "3d")}) == []
    assert kinds(date(2026, 10, 19), sent={(2, "3d"), (2, "1d")}) == []


def test_closed_and_undated_milestones_are_skipped():
    milestones = [make_milestone(3, "2026-10-20", state="closed"), make_milestone(4, None)]
    assert kinds(date(2026, 10, 19), milestones=milestones) == []


def test_non_iteration_milestones_get_reminders_too():
    release = make_milestone(20, "2026-11-17", title="Release 1")
    assert kinds(date(2026, 11, 14), milestones=[release]) == [(20, "3d", 3)]


def test_next_deadline_picks_soonest_open_milestone(milestones):
    milestone, days_left = next_deadline(milestones, date(2026, 10, 7))
    assert (milestone.title, days_left) == ("Iteration 2", 13)
    # Due today still counts as the next deadline.
    assert next_deadline(milestones, date(2026, 10, 6))[0].title == "Iteration 1"


def test_next_deadline_skips_closed_and_past(milestones):
    closed = [make_milestone(1, "2026-10-06", state="closed"), make_milestone(2, "2026-10-20")]
    assert next_deadline(closed, date(2026, 10, 1))[0].number == 2
    assert next_deadline(milestones, date(2027, 1, 1)) is None
    assert next_deadline([], date(2026, 10, 1)) is None
