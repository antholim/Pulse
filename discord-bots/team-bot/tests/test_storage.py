from datetime import date, timedelta

import pytest

from team_bot.services.storage import Storage

from conftest import utc

NOW = utc("2026-10-10T12:00:00")


def add(storage, discord_id=1, name="Ana", day=date(2026, 10, 9), hours=2.0, ref=44):
    return storage.add_work_log(discord_id, name, day, "  Did work  ", hours, ref, NOW)


def test_add_and_read_work_log(storage):
    log = add(storage)
    assert log.id == 1
    assert log.description == "Did work"
    assert log.reference == 44
    assert log.created_at == NOW
    assert storage.get_work_log(log.id) == log


def test_display_name_updates_on_next_log(storage):
    add(storage, name="Ana")
    add(storage, name="Ana L.")
    assert {log.member_name for log in storage.list_work_logs()} == {"Ana L."}


def test_list_filters_by_date_range_and_member(storage):
    add(storage, day=date(2026, 10, 1))
    add(storage, day=date(2026, 10, 7))
    add(storage, discord_id=2, name="Ben", day=date(2026, 10, 8))
    in_range = storage.list_work_logs(date(2026, 10, 7), date(2026, 10, 20))
    assert [log.work_date.day for log in in_range] == [7, 8]
    assert len(storage.list_work_logs(discord_id=2)) == 1


def test_only_the_owner_can_delete(storage):
    log = add(storage, discord_id=1)
    assert storage.delete_work_log(log.id, discord_id=2) is False
    assert storage.delete_work_log(log.id, discord_id=1) is True
    assert storage.delete_work_log(log.id, discord_id=1) is False


def test_naive_datetimes_are_rejected(storage):
    with pytest.raises(ValueError):
        storage.add_work_log(1, "Ana", date(2026, 10, 9), "x", 1, None, NOW.replace(tzinfo=None))


def test_meetings_lifecycle(storage):
    soon = storage.add_meeting("Planning", NOW + timedelta(days=2), "https://meet", 7, NOW)
    storage.add_meeting("Past", NOW - timedelta(hours=1), None, 7, NOW - timedelta(days=1))
    later = storage.add_meeting("Retro", NOW + timedelta(days=5), None, 7, NOW)

    assert [m.title for m in storage.upcoming_meetings(NOW)] == ["Planning", "Retro"]

    storage.mark_meeting_reminded(soon.id, "1d")
    reloaded = storage.get_meeting(soon.id)
    assert reloaded.reminded_1d and not reloaded.reminded_1h
    assert reloaded.starts_at == NOW + timedelta(days=2)

    assert storage.cancel_meeting(later.id) is True
    assert storage.cancel_meeting(later.id) is False
    assert storage.get_meeting(later.id) is None
    assert [m.title for m in storage.upcoming_meetings(NOW)] == ["Planning"]


def test_sent_reminders_are_idempotent(storage):
    storage.mark_reminder_sent(2, "3d", NOW)
    storage.mark_reminder_sent(2, "3d", NOW)
    storage.mark_reminder_sent(2, "1d", NOW)
    assert storage.sent_reminders() == {(2, "3d"), (2, "1d")}


def test_data_survives_reopening(tmp_path):
    path = tmp_path / "nested" / "bot.db"
    first = Storage(path)
    add(first)
    first.close()
    second = Storage(path)
    assert len(second.list_work_logs()) == 1
    second.close()
