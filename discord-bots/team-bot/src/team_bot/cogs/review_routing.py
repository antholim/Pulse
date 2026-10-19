"""Ping the team a pull request concerns and ask its members for a review (issue #76).

The bot has no public URL, so GitHub cannot tell it when a PR is opened. Instead it checks
the open PRs every REVIEW_ROUTING_SECONDS and only looks closer at the ones that changed.
Teams are set in review-teams.toml (see domain/review_teams.py). The scheduled loop and
`/run review-routing` both call `run_check`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import discord
from discord.ext import commands, tasks
from githubkit.exception import RequestFailed

from team_bot import formatting
from team_bot.config import ConfigError
from team_bot.domain.review_teams import (
    ReviewTeam,
    TeamMatch,
    load_review_teams,
    match_teams,
    reviewers_for,
)
from team_bot.services.github import PullRequest

if TYPE_CHECKING:
    from team_bot.bot import TeamBot

log = logging.getLogger(__name__)


class ReviewRoutingCog(commands.Cog):
    def __init__(self, bot: TeamBot) -> None:
        self.bot = bot
        self._teams: tuple[ReviewTeam, ...] | None = None

    async def cog_load(self) -> None:
        seconds = self.bot.settings.review_routing_seconds
        if seconds is None:
            return
        try:
            self.teams()
        except ConfigError as exc:
            log.error("PR review routing is off: %s", exc)
            return
        self.check_prs.change_interval(seconds=seconds)
        self.check_prs.start()

    async def cog_unload(self) -> None:
        self.check_prs.cancel()

    def teams(self) -> tuple[ReviewTeam, ...]:
        """The teams from review-teams.toml, read once (restart the bot after editing it)."""
        if self._teams is None:
            self._teams = load_review_teams(self.bot.settings.review_teams_path)
        return self._teams

    async def find_teams(self, pr: PullRequest) -> list[TeamMatch]:
        github = self.bot.github
        labels = [*pr.labels, *await github.closing_issue_labels(pr.number)]
        return match_teams(self.teams(), labels, await github.changed_files(pr.number))

    async def route(self, pr: PullRequest, *, again: bool = False) -> list[TeamMatch]:
        """Ping the teams this PR concerns that were not pinged for it yet (all of them with
        `again`), and request reviews from their members. Returns the teams pinged."""
        matches = await self.find_teams(pr)
        if not again:
            done = self.bot.storage.routed_teams(pr.number)
            matches = [m for m in matches if m.team.key not in done]
        if not matches:
            return []

        reviewers = reviewers_for(matches, pr.author)
        if reviewers:
            try:
                await self.bot.github.request_reviewers(pr.number, reviewers)
            except RequestFailed as exc:
                # A read-only token, or a username that is not a collaborator. Still ping.
                log.warning("Could not request reviews from %s: %s", ", ".join(reviewers), exc)

        content, title, description = formatting.review_request(pr, matches)
        roles = [discord.Object(m.team.discord_role_id) for m in matches if m.team.discord_role_id]
        await self.bot.send_to(
            self.bot.settings.review_routing_channel_id,
            content=content,
            embed=discord.Embed(
                title=title,
                url=pr.html_url,
                description=description,
                colour=discord.Colour.orange(),
            ),
            # Only the matched teams' roles, never @everyone, @here or users.
            allowed_mentions=discord.AllowedMentions(everyone=False, users=False, roles=roles),
        )
        keys = [m.team.key for m in matches]
        self.bot.storage.mark_teams_routed(pr.number, keys, datetime.now(UTC))
        log.info("PR #%d: pinged %s, requested %s", pr.number, keys, reviewers or "nobody")
        return matches

    async def run_check(self) -> list[str]:
        """Ping the teams of every open PR that is ready for review and changed since the last
        check. PRs opened before review routing was first turned on are left alone.

        Returns what was posted. A PR that fails is skipped and retried next time.
        """
        since = self.bot.storage.review_routing_since(datetime.now(UTC))
        posted = []
        for pr in await self.bot.github.open_pull_requests():
            if pr.draft or pr.created_at < since:
                continue
            if pr.updated_at and self.bot.storage.review_checked_at(pr.number) == pr.updated_at:
                continue
            try:
                matches = await self.route(pr)
            except Exception:
                log.exception("Could not route PR #%d", pr.number)
                continue
            if pr.updated_at:
                self.bot.storage.mark_review_checked(pr.number, pr.updated_at)
            if matches:
                posted.append(formatting.routing_result(pr, matches))
        return posted

    async def route_now(self, number: int) -> list[str]:
        """Ping the teams of one open PR right now, even if they were already pinged."""
        prs = await self.bot.github.open_pull_requests()
        pr = next((pr for pr in prs if pr.number == number), None)
        if pr is None:
            return []
        matches = await self.route(pr, again=True)
        return [formatting.routing_result(pr, matches)] if matches else []

    @tasks.loop(seconds=60)  # replaced by REVIEW_ROUTING_SECONDS in cog_load
    async def check_prs(self) -> None:
        try:
            await self.run_check()
        except Exception:
            # An uncaught error would stop the loop for good.
            log.exception("PR review routing failed; will retry")

    @check_prs.before_loop
    async def _wait_until_ready(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: TeamBot) -> None:
    await bot.add_cog(ReviewRoutingCog(bot))
