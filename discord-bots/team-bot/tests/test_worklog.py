from datetime import date

import pytest

from team_bot.domain.worklog import WorkLog, summarize, validate_entry

from conftest import utc

TODAY = date(2026, 10, 10)


def entry(id, discord_id, name, hours, reference=None, day=TODAY):
    return WorkLog(id, discord_id, name, day, "work", hours, reference, utc("2026-10-10T12:00:00"))


@pytest.mark.parametrize(
    ("hours", "day", "description", "expected"),
    [
        (1.5, TODAY, "Reviewed PR", None),
        (0.25, TODAY, "x", None),
        (24, TODAY, "x", None),
        (0.1, TODAY, "x", "Hours"),
        (25, TODAY, "x", "Hours"),
        (1, date(2026, 10, 11), "x", "future"),
        (1, TODAY, "   ", "empty"),
    ],
)
def test_validate_entry(hours, day, description, expected):
    error = validate_entry(hours, day, TODAY, description)
    if expected is None:
        assert error is None
    else:
        assert expected in error


def test_summarize_totals_and_orders_members():
    logs = [
        entry(1, 10, "Ana", 2, reference=44),
        entry(2, 20, "Ben", 5),
        entry(3, 10, "Ana", 1.5, reference=44),
        entry(4, 10, "Ana", 1, reference=21),
    ]
    ana, ben = summarize(logs)[1], summarize(logs)[0]
    assert (ben.member_name, ben.hours, ben.entries, ben.references) == ("Ben", 5, 1, ())
    assert (ana.hours, ana.entries, ana.references) == (4.5, 3, (21, 44))


def test_summarize_ties_sorted_by_name_and_uses_latest_name():
    logs = [entry(1, 1, "zed", 2), entry(2, 2, "Amy", 2), entry(3, 1, "Zed L.", 0)]
    names = [s.member_name for s in summarize(logs)]
    assert names == ["Amy", "Zed L."]


def test_summarize_empty():
    assert summarize([]) == []
