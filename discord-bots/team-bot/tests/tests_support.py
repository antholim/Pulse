"""Shared fakes for tests."""

from __future__ import annotations

from team_bot.domain.iterations import Milestone
from team_bot.services.github import PullRequest


class FakeGitHub:
    def __init__(
        self,
        milestones: list[Milestone] | None = None,
        pulls: list[PullRequest] | None = None,
        files: dict[int, list[str]] | None = None,
        issue_labels: dict[int, list[str]] | None = None,
    ) -> None:
        self._milestones = milestones or []
        self._pulls = pulls or []
        self.files = files or {}
        self.issue_labels = issue_labels or {}
        self.requested: list[tuple[int, list[str]]] = []
        self.fetched: list[int] = []  # PRs whose files were fetched

    async def milestones(self) -> list[Milestone]:
        return self._milestones

    async def open_pull_requests(self) -> list[PullRequest]:
        return self._pulls

    async def changed_files(self, number: int) -> list[str]:
        self.fetched.append(number)
        return self.files.get(number, [])

    async def closing_issue_labels(self, number: int) -> list[str]:
        return self.issue_labels.get(number, [])

    async def request_reviewers(self, number: int, logins: list[str]) -> None:
        self.requested.append((number, logins))
