"""Map dates to iterations and releases using the GitHub milestones.

Iteration N covers the days after Iteration N-1's due date, up to and including
its own due date. The first iteration starts FIRST_ITERATION_DAYS before it is due.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from team_bot.config import Release

ITERATION_TITLE = re.compile(r"^\s*Iteration\s+(\d+)\s*$", re.IGNORECASE)
FIRST_ITERATION_DAYS = 14


@dataclass(frozen=True)
class Milestone:
    number: int
    title: str
    state: str
    due_on: datetime | None
    html_url: str = ""

    @property
    def due_date(self) -> date | None:
        # GitHub stores milestone due dates as midnight UTC of the chosen day.
        return self.due_on.date() if self.due_on else None


@dataclass(frozen=True)
class Iteration:
    number: int
    title: str
    start: date
    end: date
    milestone: Milestone

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


@dataclass(frozen=True)
class ReleaseWindow:
    name: str
    start: date
    end: date
    first_iteration: int
    last_iteration: int


def build_iterations(milestones: Iterable[Milestone]) -> list[Iteration]:
    """Turn "Iteration N" milestones with a due date into consecutive date ranges."""
    numbered = []
    for milestone in milestones:
        match = ITERATION_TITLE.match(milestone.title)
        if match and milestone.due_date is not None:
            numbered.append((int(match.group(1)), milestone))
    numbered.sort(key=lambda pair: pair[0])

    iterations: list[Iteration] = []
    for number, milestone in numbered:
        end = milestone.due_date
        assert end is not None
        if iterations:
            start = iterations[-1].end + timedelta(days=1)
        else:
            start = end - timedelta(days=FIRST_ITERATION_DAYS - 1)
        if start > end:
            # Due dates out of order; keep a one-day window rather than an empty one.
            start = end
        iterations.append(Iteration(number, milestone.title, start, end, milestone))
    return iterations


def iteration_for(day: date, iterations: Sequence[Iteration]) -> Iteration | None:
    for iteration in iterations:
        if iteration.contains(day):
            return iteration
    return None


def find_iteration(number: int, iterations: Sequence[Iteration]) -> Iteration | None:
    return next((it for it in iterations if it.number == number), None)


def release_for(
    iteration: Iteration,
    iterations: Sequence[Iteration],
    releases: Sequence[Release],
) -> ReleaseWindow | None:
    """Return the release an iteration belongs to, with its full date range."""
    first = 1
    for release in sorted(releases, key=lambda r: r.last_iteration):
        if first <= iteration.number <= release.last_iteration:
            members = [it for it in iterations if first <= it.number <= release.last_iteration]
            return ReleaseWindow(
                name=release.name,
                start=members[0].start,
                end=members[-1].end,
                first_iteration=first,
                last_iteration=release.last_iteration,
            )
        first = release.last_iteration + 1
    return None
