from datetime import UTC, datetime

import pytest

from app.ingestion.connector import RawRecord, is_after, parse_timestamp

WATERMARK = datetime(2026, 10, 1, tzinfo=UTC)


def record(updated_at):
    return RawRecord(entity_kind="organization", external_id="1", updated_at=updated_at, payload={})


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-01T12:30:00Z", datetime(2026, 10, 1, 12, 30, tzinfo=UTC)),
        ("2026-10-01T12:30:00+00:00", datetime(2026, 10, 1, 12, 30, tzinfo=UTC)),
        ("2026-10-01T12:30:00", datetime(2026, 10, 1, 12, 30, tzinfo=UTC)),
        ("not a date", None),
        (None, None),
        (1727787000, None),
    ],
)
def test_parse_timestamp(value, expected):
    assert parse_timestamp(value) == expected


def test_full_sync_includes_every_record():
    assert is_after(record(datetime(2000, 1, 1, tzinfo=UTC)), None)


def test_incremental_sync_keeps_only_newer_records():
    assert is_after(record(datetime(2026, 10, 2, tzinfo=UTC)), WATERMARK)
    assert not is_after(record(WATERMARK), WATERMARK)
    assert not is_after(record(datetime(2026, 9, 30, tzinfo=UTC)), WATERMARK)


def test_record_without_timestamp_is_always_included():
    assert is_after(record(None), WATERMARK)
