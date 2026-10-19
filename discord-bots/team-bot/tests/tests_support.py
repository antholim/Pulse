"""Shared fakes for tests."""

from __future__ import annotations

from datetime import datetime

from team_bot.domain.iterations import Milestone
from team_bot.services.github import PullRequest, ReviewContext


class FakeGitHub:
    def __init__(
        self,
        milestones: list[Milestone] | None = None,
        pulls: list[PullRequest] | None = None,
        issue_labels: dict[int, list[str]] | None = None,
        reopened_at: dict[int, datetime] | None = None,
    ) -> None:
        self._milestones = milestones or []
        self._pulls = pulls or []
        self.issue_labels = issue_labels or {}
        self.reopened_at = reopened_at or {}
        self.requested: list[tuple[int, list[str]]] = []
        self.fetched: list[int] = []  # PRs whose review context was fetched

    async def milestones(self) -> list[Milestone]:
        return self._milestones

    async def open_pull_requests(self) -> list[PullRequest]:
        return self._pulls

    async def review_context(self, number: int) -> ReviewContext:
        self.fetched.append(number)
        return ReviewContext(tuple(self.issue_labels.get(number, [])), self.reopened_at.get(number))

    async def request_reviewers(self, number: int, logins: list[str]) -> None:
        self.requested.append((number, logins))
