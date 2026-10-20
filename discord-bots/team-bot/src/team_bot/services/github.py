"""Small GitHub client: milestones, open pull requests and what review routing needs.

Responses are mapped from raw JSON into our own dataclasses, so the rest of the
bot (and the tests) never depend on githubkit's models.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from githubkit import AppInstallationAuthStrategy, GitHub, TokenAuthStrategy

from team_bot.config import GitHubAuth
from team_bot.domain.iterations import Milestone

MILESTONE_CACHE_SECONDS = 600


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    author: str
    html_url: str
    draft: bool
    created_at: datetime
    requested_reviewers: tuple[str, ...]
    labels: tuple[str, ...] = ()
    updated_at: datetime | None = None


@dataclass(frozen=True)
class ReviewContext:
    """What review routing needs beyond the PR itself."""

    issue_labels: tuple[str, ...]  # labels of the issues the PR closes ("Closes #12")
    reopened_at: datetime | None  # when the PR was last reopened, if ever


class GitHubReader(Protocol):
    """What the cogs need from GitHub. Tests pass a fake that implements this."""

    async def milestones(self) -> list[Milestone]: ...

    async def open_pull_requests(self) -> list[PullRequest]: ...

    # Review routing (#76)

    async def review_context(self, number: int) -> ReviewContext: ...

    async def request_reviewers(self, number: int, logins: list[str]) -> None: ...


REVIEW_CONTEXT_QUERY = """
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      closingIssuesReferences(first: 20) {
        nodes { labels(first: 50) { nodes { name } } }
      }
      timelineItems(last: 1, itemTypes: [REOPENED_EVENT]) {
        nodes { ... on ReopenedEvent { createdAt } }
      }
    }
  }
}
"""


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def milestone_from_json(data: dict[str, Any]) -> Milestone:
    return Milestone(
        number=data["number"],
        title=data["title"],
        state=data["state"],
        due_on=_parse_datetime(data.get("due_on")),
        html_url=data.get("html_url", ""),
    )


def pull_request_from_json(data: dict[str, Any]) -> PullRequest:
    created = _parse_datetime(data["created_at"])
    assert created is not None
    reviewers = [user["login"] for user in data.get("requested_reviewers") or []]
    reviewers += [team["name"] for team in data.get("requested_teams") or []]
    return PullRequest(
        number=data["number"],
        title=data["title"],
        author=(data.get("user") or {}).get("login", "unknown"),
        html_url=data["html_url"],
        draft=bool(data.get("draft")),
        created_at=created,
        requested_reviewers=tuple(reviewers),
        labels=tuple(label["name"] for label in data.get("labels") or []),
        updated_at=_parse_datetime(data.get("updated_at")),
    )


def build_client(auth: GitHubAuth) -> GitHub:
    if auth.token:
        return GitHub(TokenAuthStrategy(auth.token))
    assert auth.app_id and auth.private_key and auth.installation_id
    return GitHub(AppInstallationAuthStrategy(auth.app_id, auth.private_key, auth.installation_id))


class GitHubService:
    def __init__(self, client: GitHub, owner: str, repo: str) -> None:
        self._client = client
        self._owner = owner
        self._repo = repo
        self._milestones: list[Milestone] | None = None
        self._milestones_at = 0.0

    async def milestones(self) -> list[Milestone]:
        """All milestones (open and closed), cached for a few minutes."""
        fresh = time.monotonic() - self._milestones_at < MILESTONE_CACHE_SECONDS
        if self._milestones is not None and fresh:
            return self._milestones
        response = await self._client.rest.issues.async_list_milestones(
            self._owner, self._repo, state="all", per_page=100
        )
        self._milestones = [milestone_from_json(item) for item in response.json()]
        self._milestones_at = time.monotonic()
        return self._milestones

    async def open_pull_requests(self) -> list[PullRequest]:
        response = await self._client.rest.pulls.async_list(
            self._owner, self._repo, state="open", per_page=100
        )
        return [pull_request_from_json(item) for item in response.json()]

    async def review_context(self, number: int) -> ReviewContext:
        """Labels of the issues this PR closes, and when it was last reopened (one query)."""
        data = await self._client.async_graphql(
            REVIEW_CONTEXT_QUERY,
            {"owner": self._owner, "repo": self._repo, "number": number},
        )
        pull = (data.get("repository") or {}).get("pullRequest") or {}
        issues = (pull.get("closingIssuesReferences") or {}).get("nodes") or []
        reopens = (pull.get("timelineItems") or {}).get("nodes") or []
        return ReviewContext(
            issue_labels=tuple(
                label["name"] for issue in issues for label in issue["labels"]["nodes"]
            ),
            reopened_at=_parse_datetime(reopens[-1].get("createdAt")) if reopens else None,
        )

    async def request_reviewers(self, number: int, logins: list[str]) -> None:
        """Needs a token with Pull requests: write."""
        await self._client.rest.pulls.async_request_reviewers(
            self._owner, self._repo, number, reviewers=logins
        )
