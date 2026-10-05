"""Shared fakes for tests."""

from __future__ import annotations

from team_bot.domain.iterations import Milestone
from team_bot.services.github import PullRequest


class FakeGitHub:
    def __init__(
        self, milestones: list[Milestone] | None = None, pulls: list[PullRequest] | None = None
    ) -> None:
        self._milestones = milestones or []
        self._pulls = pulls or []

    async def milestones(self) -> list[Milestone]:
        return self._milestones

    async def open_pull_requests(self) -> list[PullRequest]:
        return self._pulls
