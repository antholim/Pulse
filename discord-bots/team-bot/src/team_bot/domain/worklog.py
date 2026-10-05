"""Work log entries and per-member summaries."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime

MIN_HOURS = 0.25
MAX_HOURS = 24.0


@dataclass(frozen=True)
class WorkLog:
    id: int
    discord_id: int
    member_name: str
    work_date: date
    description: str
    hours: float
    reference: int | None
    created_at: datetime


@dataclass(frozen=True)
class MemberSummary:
    discord_id: int
    member_name: str
    hours: float
    entries: int
    references: tuple[int, ...]


def validate_entry(hours: float, work_date: date, today: date, description: str) -> str | None:
    """Return an error message for an invalid entry, or None when it is fine."""
    if not description.strip():
        return "Description cannot be empty."
    if not MIN_HOURS <= hours <= MAX_HOURS:
        return f"Hours must be between {MIN_HOURS:g} and {MAX_HOURS:g}."
    if work_date > today:
        return "You cannot log work for a future date."
    return None


def summarize(logs: Iterable[WorkLog]) -> list[MemberSummary]:
    """Total hours per member, highest first, ties broken by name."""
    totals: dict[int, dict] = {}
    for log in logs:
        bucket = totals.setdefault(
            log.discord_id,
            {"name": log.member_name, "hours": 0.0, "entries": 0, "refs": set()},
        )
        bucket["name"] = log.member_name  # keep the most recent display name
        bucket["hours"] += log.hours
        bucket["entries"] += 1
        if log.reference is not None:
            bucket["refs"].add(log.reference)

    summaries = [
        MemberSummary(
            discord_id=discord_id,
            member_name=data["name"],
            hours=round(data["hours"], 2),
            entries=data["entries"],
            references=tuple(sorted(data["refs"])),
        )
        for discord_id, data in totals.items()
    ]
    return sorted(summaries, key=lambda s: (-s.hours, s.member_name.lower()))
