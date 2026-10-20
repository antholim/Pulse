"""Ping the team a pull request concerns and ask its members for a review (issue #76).

The bot has no public URL, so GitHub cannot tell it when a PR is opened. Instead it checks
the open PRs every REVIEW_ROUTING_SECONDS and only looks closer at the ones that changed.
Teams are set in review-teams.toml (see domain/review_teams.py). The scheduled loop and
`/run review-routing` both call `run_check`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
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
from team_bot.services.github import PullRequest, ReviewContext

if TYPE_CHECKING:
    from team_bot.bot import TeamBot

log = logging.getLogger(__name__)

# The first time routing runs, PRs opened up to this long before are still routed (a PR
# opened just before starting the bot); older ones are left alone.
FIRST_RUN_GRACE = timedelta(hours=1)


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

    def role_id(self, team: ReviewTeam) -> int | None:
        """The team's Discord role: its ID, or found by name (any case) in the server."""
        role = team.discord_role
        if role is None or isinstance(role, int):
            return role
        guild = self.bot.get_guild(self.bot.settings.guild_id)
        roles = guild.roles if guild else []
        found = next((r for r in roles if r.name.casefold() == role.casefold()), None)
        if found is None:
            log.warning("No Discord role named %r for %s, naming the team instead", role, team.name)
            return None
        return found.id

    def find_teams(self, pr: PullRequest, context: ReviewContext) -> list[TeamMatch]:
        return match_teams(self.teams(), [*pr.labels, *context.issue_labels])

    def reopened(self, pr: PullRequest, context: ReviewContext, since: datetime) -> bool:
        """Reopened since its teams were last pinged (or ever, for a PR never pinged)."""
        if context.reopened_at is None or context.reopened_at < since:
            return False
        last = self.bot.storage.last_routed_at(pr.number)
        return last is None or context.reopened_at > last

    async def route(
        self,
        pr: PullRequest,
        context: ReviewContext | None = None,
        *,
        again: bool = False,
        reopened: bool = False,
    ) -> list[TeamMatch]:
        """Ping the teams this PR concerns that were not pinged for it yet (all of them with
        `again`), and request reviews from their members. Returns the teams pinged."""
        if context is None:
            context = await self.bot.github.review_context(pr.number)
        matches = self.find_teams(pr, context)
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

        role_ids = {m.team.key: role for m in matches if (role := self.role_id(m.team))}
        content, title, description = formatting.review_request(
            pr, matches, role_ids, reopened=reopened
        )
        roles = [discord.Object(role) for role in role_ids.values()]
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
        check. A reopened PR pings all its teams again. PRs opened well before review
        routing first ran are left alone, unless they are reopened after it.

        Returns what was posted. A PR that fails is skipped and retried next time.
        """
        storage = self.bot.storage
        since = storage.review_routing_since(datetime.now(UTC) - FIRST_RUN_GRACE)
        posted = []
        for pr in await self.bot.github.open_pull_requests():
            if pr.draft:
                continue
            if pr.updated_at and storage.review_checked_at(pr.number) == pr.updated_at:
                continue
            try:
                context = await self.bot.github.review_context(pr.number)
                reopened = self.reopened(pr, context, since)
                if reopened:
                    storage.forget_routed_teams(pr.number)
                matches = []
                if reopened or pr.created_at >= since:
                    matches = await self.route(pr, context, reopened=reopened)
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
