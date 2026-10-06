"""SQLite storage for members, work logs, meetings and sent reminders.

The data is tiny and every query is fast, so the standard library sqlite3 module
is used directly from the event loop. Datetimes are stored as UTC ISO strings.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from team_bot.domain.meetings import Meeting
from team_bot.domain.worklog import WorkLog

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    discord_id    INTEGER PRIMARY KEY,
    display_name  TEXT NOT NULL,
    github_login  TEXT
);

CREATE TABLE IF NOT EXISTS work_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_id   INTEGER NOT NULL REFERENCES members(discord_id),
    work_date    TEXT NOT NULL,
    description  TEXT NOT NULL,
    hours        REAL NOT NULL CHECK (hours > 0),
    reference    INTEGER,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_work_logs_date ON work_logs(work_date);

CREATE TABLE IF NOT EXISTS meetings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    starts_at    TEXT NOT NULL,
    link         TEXT,
    created_by   INTEGER NOT NULL,
    created_at   TEXT NOT NULL,
    reminded_1d  INTEGER NOT NULL DEFAULT 0,
    reminded_1h  INTEGER NOT NULL DEFAULT 0,
    cancelled    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reminders_sent (
    milestone_number  INTEGER NOT NULL,
    kind              TEXT NOT NULL,
    sent_at           TEXT NOT NULL,
    PRIMARY KEY (milestone_number, kind)
);
"""


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Datetimes must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


class Storage:
    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # Members

    def upsert_member(self, discord_id: int, display_name: str) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO members (discord_id, display_name) VALUES (?, ?)
                ON CONFLICT(discord_id) DO UPDATE SET display_name = excluded.display_name
                """,
                (discord_id, display_name),
            )

    # Work logs

    def add_work_log(
        self,
        discord_id: int,
        display_name: str,
        work_date: date,
        description: str,
        hours: float,
        reference: int | None,
        now: datetime,
    ) -> WorkLog:
        self.upsert_member(discord_id, display_name)
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO work_logs (discord_id, work_date, description, hours, reference,
                                       created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    discord_id,
                    work_date.isoformat(),
                    description.strip(),
                    hours,
                    reference,
                    _utc_iso(now),
                ),
            )
        log = self.get_work_log(cursor.lastrowid)
        assert log is not None
        return log

    def get_work_log(self, log_id: int) -> WorkLog | None:
        row = self._conn.execute(_WORK_LOG_SELECT + " WHERE w.id = ?", (log_id,)).fetchone()
        return _row_to_work_log(row) if row else None

    def delete_work_log(self, log_id: int, discord_id: int) -> bool:
        """Delete an entry, only if it belongs to discord_id."""
        with self._conn:
            cursor = self._conn.execute(
                "DELETE FROM work_logs WHERE id = ? AND discord_id = ?", (log_id, discord_id)
            )
        return cursor.rowcount == 1

    def list_work_logs(
        self,
        start: date | None = None,
        end: date | None = None,
        discord_id: int | None = None,
    ) -> list[WorkLog]:
        clauses, params = [], []
        if start is not None:
            clauses.append("w.work_date >= ?")
            params.append(start.isoformat())
        if end is not None:
            clauses.append("w.work_date <= ?")
            params.append(end.isoformat())
        if discord_id is not None:
            clauses.append("w.discord_id = ?")
            params.append(discord_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(
            _WORK_LOG_SELECT + where + " ORDER BY w.work_date, w.id", params
        ).fetchall()
        return [_row_to_work_log(row) for row in rows]

    # Meetings

    def add_meeting(
        self, title: str, starts_at: datetime, link: str | None, created_by: int, now: datetime
    ) -> Meeting:
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO meetings (title, starts_at, link, created_by, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (title.strip(), _utc_iso(starts_at), link, created_by, _utc_iso(now)),
            )
        meeting = self.get_meeting(cursor.lastrowid)
        assert meeting is not None
        return meeting

    def get_meeting(self, meeting_id: int) -> Meeting | None:
        row = self._conn.execute(
            "SELECT * FROM meetings WHERE id = ? AND cancelled = 0", (meeting_id,)
        ).fetchone()
        return _row_to_meeting(row) if row else None

    def upcoming_meetings(self, now: datetime) -> list[Meeting]:
        rows = self._conn.execute(
            "SELECT * FROM meetings WHERE cancelled = 0 AND starts_at > ? ORDER BY starts_at",
            (_utc_iso(now),),
        ).fetchall()
        return [_row_to_meeting(row) for row in rows]

    def cancel_meeting(self, meeting_id: int) -> bool:
        with self._conn:
            cursor = self._conn.execute(
                "UPDATE meetings SET cancelled = 1 WHERE id = ? AND cancelled = 0", (meeting_id,)
            )
        return cursor.rowcount == 1

    def mark_meeting_reminded(self, meeting_id: int, kind: str) -> None:
        column = {"1d": "reminded_1d", "1h": "reminded_1h"}[kind]
        with self._conn:
            self._conn.execute(f"UPDATE meetings SET {column} = 1 WHERE id = ?", (meeting_id,))

    # Milestone reminders

    def sent_reminders(self) -> set[tuple[int, str]]:
        rows = self._conn.execute("SELECT milestone_number, kind FROM reminders_sent").fetchall()
        return {(row["milestone_number"], row["kind"]) for row in rows}

    def mark_reminder_sent(self, milestone_number: int, kind: str, now: datetime) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO reminders_sent (milestone_number, kind, sent_at)
                VALUES (?, ?, ?)
                """,
                (milestone_number, kind, _utc_iso(now)),
            )


_WORK_LOG_SELECT = """
SELECT w.id, w.discord_id, m.display_name, w.work_date, w.description, w.hours,
       w.reference, w.created_at
FROM work_logs w JOIN members m ON m.discord_id = w.discord_id
"""


def _row_to_work_log(row: sqlite3.Row) -> WorkLog:
    return WorkLog(
        id=row["id"],
        discord_id=row["discord_id"],
        member_name=row["display_name"],
        work_date=date.fromisoformat(row["work_date"]),
        description=row["description"],
        hours=row["hours"],
        reference=row["reference"],
        created_at=_parse_utc(row["created_at"]),
    )


def _row_to_meeting(row: sqlite3.Row) -> Meeting:
    return Meeting(
        id=row["id"],
        title=row["title"],
        starts_at=_parse_utc(row["starts_at"]),
        link=row["link"],
        created_by=row["created_by"],
        created_at=_parse_utc(row["created_at"]),
        reminded_1d=bool(row["reminded_1d"]),
        reminded_1h=bool(row["reminded_1h"]),
    )
