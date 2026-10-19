"""PR review routing (#76): the polling job and /run review-routing."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from githubkit.exception import RequestFailed

from team_bot import formatting
from team_bot.cogs.review_routing import ReviewRoutingCog
from team_bot.cogs.run import RunCog
from team_bot.config import Settings
from team_bot.domain.review_teams import ReviewTeam, match_teams
from team_bot.services.github import PullRequest

from conftest import utc
from tests_support import FakeGitHub

ROUTING_CHANNEL = 5
ENV = {
    "DISCORD_TOKEN": "x",
    "DISCORD_GUILD_ID": "1",
    "GITHUB_REPO": "antholim/Pulse",
    "REMINDERS_CHANNEL_ID": "2",
    "REVIEW_ROUTING_CHANNEL_ID": str(ROUTING_CHANNEL),
    "GITHUB_TOKEN": "t",
}
TEAMS_TOML = """
[teams.data]
name = "Data & AI team"
discord_role = "data team"
members = ["alice", "bob"]
labels = ["data"]

[teams.swe]
name = "SWE team"
discord_role = 222
members = ["carol"]
labels = ["swe", "Dashboard"]

[teams.infra]
name = "Infra team"
labels = ["infra"]
"""
OPENED = utc("2026-10-19T12:00:00")


class FakeBot:
    def __init__(self, storage, github, teams_path):
        self.settings = replace(Settings.from_env(ENV), review_teams_path=teams_path)
        self.storage = storage
        self.github = github
        self.sent: list[tuple[int, dict]] = []
        self.cogs = {}

    async def send_to(self, channel_id, **kwargs):
        self.sent.append((channel_id, kwargs))

    def get_guild(self, guild_id):
        assert guild_id == 1
        return SimpleNamespace(roles=[SimpleNamespace(id=111, name="Data Team")])

    def get_cog(self, name):
        return self.cogs.get(name)


def make_pr(number=12, **changes) -> PullRequest:
    fields = dict(
        number=number,
        title="Add fuzzy matching",
        author="alice",
        html_url=f"https://github.com/antholim/Pulse/pull/{number}",
        draft=False,
        created_at=OPENED,
        requested_reviewers=(),
        labels=(),
        updated_at=OPENED,
    )
    return PullRequest(**(fields | changes))


@pytest.fixture
def teams_path(tmp_path):
    path = tmp_path / "review-teams.toml"
    path.write_text(TEAMS_TOML, encoding="utf-8")
    return path


@pytest.fixture
def github():
    return FakeGitHub(
        pulls=[make_pr(labels=("Dashboard",))],
        issue_labels={12: ["data", "Release 1"]},
    )


@pytest.fixture
def bot(storage, github, teams_path):
    # Routing started before the PRs were opened, so they are all in scope.
    storage.review_routing_since(OPENED - timedelta(days=1))
    return FakeBot(storage, github, teams_path)


@pytest.fixture
def cog(bot):
    return ReviewRoutingCog(bot)


async def test_pings_matched_teams_once(bot, github, cog):
    assert await cog.run_check() == ["#12 Add fuzzy matching: Data & AI team, SWE team"]

    channel, message = bot.sent[0]
    assert channel == ROUTING_CHANNEL
    assert message["content"] == "<@&111> <@&222> review requested"
    assert message["embed"].url == "https://github.com/antholim/Pulse/pull/12"
    mentions = message["allowed_mentions"]
    assert not mentions.everyone and not mentions.users
    assert [role.id for role in mentions.roles] == [111, 222]
    assert github.requested == [(12, ["bob", "carol"])]  # alice wrote the PR
    assert bot.storage.routed_teams(12) == {"data", "swe"}

    # Next check: the PR has not changed, so GitHub is not asked about it again.
    assert await cog.run_check() == []
    assert github.fetched == [12]
    assert len(bot.sent) == 1


async def test_changed_pr_pings_only_new_teams(bot, github, cog):
    await cog.run_check()
    github._pulls = [make_pr(labels=("infra",), updated_at=OPENED + timedelta(hours=1))]

    assert await cog.run_check() == ["#12 Add fuzzy matching: Infra team"]
    assert bot.sent[1][1]["content"] == "**Infra team** review requested"  # no role set
    assert github.requested == [(12, ["bob", "carol"])]  # infra has no members listed
    assert github.fetched == [12, 12]


async def test_skips_drafts_and_old_prs(bot, github, cog):
    github._pulls = [
        make_pr(1, draft=True, labels=("data",)),
        make_pr(2, created_at=OPENED - timedelta(days=2), labels=("data",)),
        make_pr(4, labels=("data",), updated_at=None),
    ]
    assert await cog.run_check() == ["#4 Add fuzzy matching: Data & AI team"]
    assert github.fetched == [2, 4]  # the old PR is looked at once, in case it was reopened
    # Without updated_at the PR is checked every time, but each team is still pinged once.
    assert await cog.run_check() == []
    assert len(bot.sent) == 1


async def test_review_request_failure_still_pings(bot, github, cog, caplog):
    async def refuse(number, logins):
        request = httpx.Request("POST", "https://api.github.com")
        response = httpx.Response(403, request=request)
        raise RequestFailed(SimpleNamespace(raw_request=request, raw_response=response))

    github.request_reviewers = refuse
    assert len(await cog.run_check()) == 1
    assert "Could not request reviews from bob, carol" in caplog.text
    assert len(bot.sent) == 1


async def test_a_failing_pr_is_retried_next_time(bot, cog, monkeypatch):
    sends = bot.send_to

    async def broken(channel_id, **kwargs):
        raise RuntimeError("Discord is down")

    bot.send_to = broken
    monkeypatch.setattr("team_bot.cogs.review_routing.log.exception", lambda *a, **k: None)
    assert await cog.run_check() == []
    assert bot.storage.routed_teams(12) == set()
    bot.send_to = sends
    assert len(await cog.run_check()) == 1


async def test_first_check_ignores_prs_already_open(storage, github, teams_path):
    bot = FakeBot(storage, github, teams_path)  # routing never ran before
    assert await ReviewRoutingCog(bot).run_check() == []
    assert bot.sent == []


async def test_first_check_routes_a_pr_opened_just_before(storage, github, teams_path):
    just_now = datetime.now(UTC) - timedelta(minutes=30)
    github._pulls = [make_pr(created_at=just_now, updated_at=just_now)]
    bot = FakeBot(storage, github, teams_path)  # routing never ran before
    assert len(await ReviewRoutingCog(bot).run_check()) == 1


async def test_route_now_pings_again(bot, github, cog):
    await cog.run_check()
    assert await cog.route_now(12) == ["#12 Add fuzzy matching: Data & AI team, SWE team"]
    assert len(bot.sent) == 2
    assert await cog.route_now(99) == []  # not an open PR


async def test_cog_load_starts_the_loop_only_when_configured(bot, teams_path, caplog):
    cog = ReviewRoutingCog(bot)
    started = []
    cog.check_prs.start = lambda: started.append(True)
    await cog.cog_load()
    assert started == [True]
    assert cog.check_prs.seconds == 60
    assert [team.key for team in cog.teams()] == ["data", "swe", "infra"]

    bot.settings = replace(bot.settings, review_routing_seconds=None)
    off = ReviewRoutingCog(bot)
    await off.cog_load()
    assert off._teams is None

    bot.settings = replace(
        bot.settings, review_routing_seconds=60, review_teams_path=teams_path.with_name("x")
    )
    broken = ReviewRoutingCog(bot)
    await broken.cog_load()
    assert "PR review routing is off: Cannot read" in caplog.text
    await broken.cog_unload()


async def test_loop_survives_errors(cog, monkeypatch):
    async def boom():
        raise RuntimeError("GitHub unreachable")

    monkeypatch.setattr(cog, "run_check", boom)
    monkeypatch.setattr("team_bot.cogs.review_routing.log.exception", lambda *a, **k: None)
    await cog.check_prs.coro(cog)  # does not raise


class FakeInteraction:
    user = "tester"

    def __init__(self):
        self.replies = []
        interaction = self

        class Response:
            async def defer(self, ephemeral=False):
                pass

        class Followup:
            async def send(self, content=None, ephemeral=False, **kwargs):
                interaction.replies.append(content)

        self.response = Response()
        self.followup = Followup()


async def test_run_review_routing(bot, cog):
    bot.cogs["ReviewRoutingCog"] = cog
    run_cog = RunCog(bot)
    interaction = FakeInteraction()
    await run_cog.review_routing.callback(run_cog, interaction, None)
    assert interaction.replies[0] == (
        "Ran review routing: posted 1.\n- #12 Add fuzzy matching: Data & AI team, SWE team"
    )
    await run_cog.review_routing.callback(run_cog, interaction, None)
    assert interaction.replies[1] == "Ran review routing: nothing was due."
    await run_cog.review_routing.callback(run_cog, interaction, 12)
    assert interaction.replies[2].startswith("Ran review routing: posted 1.")


def test_text_helpers():
    data = ReviewTeam("data", "Data team", (), ("data",))
    matches = match_teams([data], ["data"])
    assert formatting.routing_result(make_pr(), matches) == "#12 Add fuzzy matching: Data team"
    assert "Review pings" in formatting.automatic_posts(None, review_routing=True)
    assert "PR review pings: turned off" in formatting.automatic_posts(None)


def test_routing_settings():
    settings = Settings.from_env(ENV)
    assert settings.review_routing_channel_id == ROUTING_CHANNEL
    assert settings.review_routing_seconds == 60
    assert str(settings.review_teams_path) == "review-teams.toml"
    defaults = Settings.from_env(
        ENV | {"REVIEW_ROUTING_CHANNEL_ID": "", "PR_SUMMARY_CHANNEL_ID": "3"}
    )
    assert defaults.review_routing_channel_id == 3
    assert Settings.from_env(ENV | {"REVIEW_ROUTING_SECONDS": "0"}).review_routing_seconds is None
    assert Settings.from_env(ENV | {"REVIEW_ROUTING_SECONDS": ""}).review_routing_seconds is None
    with pytest.raises(ValueError, match="at least 30"):
        Settings.from_env(ENV | {"REVIEW_ROUTING_SECONDS": "5"})


def test_relative_paths_follow_the_env_file_folder(tmp_path):
    settings = Settings.from_env(ENV, base_dir=tmp_path)
    assert settings.review_teams_path == tmp_path / "review-teams.toml"
    assert settings.db_path == tmp_path / "data" / "team-bot.db"
    absolute = Settings.from_env(ENV | {"DB_PATH": str(tmp_path / "x.db")}, base_dir=Path("y"))
    assert absolute.db_path == tmp_path / "x.db"


def test_storage_routing_state(storage):
    first = utc("2026-10-19T00:00:00")
    assert storage.review_routing_since(first) == first
    assert storage.review_routing_since(first + timedelta(days=1)) == first  # kept
    storage.mark_teams_routed(1, ["data", "swe"], first)
    storage.mark_teams_routed(1, ["data"], first)
    assert storage.routed_teams(1) == {"data", "swe"}
    assert storage.review_checked_at(1) is None
    storage.mark_review_checked(1, first)
    storage.mark_review_checked(1, first + timedelta(hours=1))
    assert storage.review_checked_at(1) == first + timedelta(hours=1)


async def test_role_not_found_names_the_team(bot, github, cog, caplog):
    cog._teams = tuple(
        replace(team, discord_role="Data People") if team.key == "data" else team
        for team in cog.teams()
    )
    await cog.run_check()
    assert bot.sent[0][1]["content"] == "**Data & AI team** <@&222> review requested"
    assert [role.id for role in bot.sent[0][1]["allowed_mentions"].roles] == [222]
    assert "No Discord role named 'Data People' for Data & AI team" in caplog.text


async def test_role_lookup_without_the_server(bot, cog):
    bot.get_guild = lambda guild_id: None  # not connected yet
    assert cog.role_id(cog.teams()[0]) is None


async def test_reopened_pr_pings_every_team_again(bot, github, cog):
    await cog.run_check()
    assert len(bot.sent) == 1
    bot.storage.forget_routed_teams(12)  # pretend that first ping was at OPENED
    bot.storage.mark_teams_routed(12, ["data", "swe"], OPENED)
    # Closed, then reopened an hour later: GitHub bumps updated_at.
    reopened = OPENED + timedelta(hours=1)
    github._pulls = [make_pr(labels=("Dashboard",), updated_at=reopened)]
    github.reopened_at = {12: reopened}

    assert await cog.run_check() == ["#12 Add fuzzy matching: Data & AI team, SWE team"]
    assert bot.sent[1][1]["content"] == "<@&111> <@&222> review requested (PR reopened)"
    assert github.requested[-1] == (12, ["bob", "carol"])

    # Any later change: the reopen was already handled.
    github._pulls = [make_pr(labels=("Dashboard",), updated_at=reopened + timedelta(minutes=5))]
    assert await cog.run_check() == []
    assert len(bot.sent) == 2


async def test_old_pr_reopened_after_routing_started_is_pinged(bot, github, cog):
    old = OPENED - timedelta(days=30)
    github._pulls = [make_pr(created_at=old, updated_at=old)]
    assert await cog.run_check() == []  # too old, never pinged
    github._pulls = [make_pr(created_at=OPENED - timedelta(days=30), updated_at=OPENED)]
    github.reopened_at = {12: OPENED}
    assert len(await cog.run_check()) == 1
    assert "(PR reopened)" in bot.sent[0][1]["content"]


async def test_reopen_before_routing_started_does_not_count(bot, github, cog):
    github.reopened_at = {12: OPENED - timedelta(days=5)}  # routing started a day before OPENED
    await cog.run_check()
    assert "reopened" not in bot.sent[0][1]["content"]


def test_storage_last_routed_and_forget(storage):
    first = utc("2026-10-19T00:00:00")
    assert storage.last_routed_at(1) is None
    storage.mark_teams_routed(1, ["data"], first)
    storage.mark_teams_routed(1, ["swe"], first + timedelta(hours=1))
    assert storage.last_routed_at(1) == first + timedelta(hours=1)
    storage.forget_routed_teams(1)
    assert storage.routed_teams(1) == set()


async def test_pr_without_team_label_pings_every_team(bot, github, cog):
    github._pulls = [make_pr(labels=("Release 1",))]
    github.issue_labels = {}
    assert await cog.run_check() == ["#12 Add fuzzy matching: Data & AI team, SWE team, Infra team"]
    message = bot.sent[0][1]
    assert message["content"] == "<@&111> <@&222> **Infra team** review requested"
    assert "No team label on this PR, so every team is asked" in message["embed"].description
    assert github.requested == [(12, ["bob", "carol"])]

    # Labelling it afterwards does not ping again: every team was already asked.
    github._pulls = [make_pr(labels=("data",), updated_at=OPENED + timedelta(hours=1))]
    assert await cog.run_check() == []
