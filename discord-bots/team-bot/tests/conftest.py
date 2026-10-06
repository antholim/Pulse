from __future__ import annotations

from datetime import UTC, datetime

import pytest

from team_bot.config import Release
from team_bot.domain.iterations import Milestone, build_iterations
from team_bot.services.storage import Storage

# The real Pulse milestone due dates (Iterations 1 to 6).
DUE_DATES = ["2026-10-06", "2026-10-20", "2026-11-03", "2026-11-17", "2026-12-01", "2026-12-15"]

RELEASES = (Release("Release 1", 4), Release("Release 2", 8), Release("Final Release", 13))


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def make_milestone(number: int, due: str | None, title: str | None = None, state: str = "open"):
    return Milestone(
        number=number,
        title=title or f"Iteration {number}",
        state=state,
        due_on=utc(due + "T00:00:00") if due else None,
        html_url=f"https://github.com/antholim/Pulse/milestone/{number}",
    )


@pytest.fixture
def milestones() -> list[Milestone]:
    return [make_milestone(i, due) for i, due in enumerate(DUE_DATES, start=1)]


@pytest.fixture
def iterations(milestones):
    return build_iterations(milestones)


@pytest.fixture
def storage():
    store = Storage(":memory:")
    yield store
    store.close()
