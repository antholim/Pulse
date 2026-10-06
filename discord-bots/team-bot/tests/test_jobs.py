"""The scheduled jobs and the /run commands that trigger them.

A fake bot records what would be posted to Discord, and the clock is frozen by
replacing `datetime` in each cog module.
"""

from datetime import datetime, timedelta

import pytest

from team_bot.cogs import deadlines as deadlines_module
from team_bot.cogs import meetings as meetings_module
from team_bot.cogs import pr_summary as pr_summary_module
from team_bot.cogs import run as run_module
from team_bot.cogs.deadlines import DeadlinesCog
from team_bot.cogs.meetings import MeetingsCog
from team_bot.cogs.pr_summary import PRSummaryCog
from team_bot.cogs.run import RunCog
from team_bot.config import Settings
from team_bot.services.github import PullRequest

from conftest import make_milestone, utc
from tests_support import FakeGitHub

ENV = {
    "DISCORD_TOKEN": "x",
    "DISCORD_GUILD_ID": "1",
    "GITHUB_REPO": "antholim/Pulse",
    "REMINDERS_CHANNEL_ID": "2",
    "PR_SUMMARY_CHANNEL_ID": "3",
    "PR_SUMMARY_ROLE_ID": "4",
    "GITHUB_TOKEN": "t",
}
REMINDERS, SUMMARY = 2, 3


class FakeBot:
    def __init__(self, storage, github):
        self.settings = Settings.from_env(ENV)
        self.storage = storage
        self.github = github
        self.sent: list[tuple[int, dict]] = []
        self.fail_sends = False
        self.cogs = {}

    async def send_to(self, channel_id, **kwargs):
        if self.fail_sends:
            raise RuntimeError("Discord is down")
        self.sent.append((channel_id, kwargs))

    def get_cog(self, name):
        return self.cogs.get(name)


class BrokenGitHub(FakeGitHub):
    async def milestones(self):
        raise RuntimeError("GitHub unreachable")


def freeze(monkeypatch, moment: datetime):
    """Make datetime.now() in every cog return `moment` (an aware datetime)."""

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz) if tz else moment

    for module in (deadlines_module, meetings_module, pr_summary_module):
        monkeypatch.setattr(module, "datetime", Frozen)


def toronto(text: str) -> datetime:
    # Oct and Nov 2026 dates used here are before the clock change: Toronto is UTC-4.
    return utc(text) + timedelta(hours=4)


@pytest.fixture
def milestones():
    dues = ["2026-10-06", "2026-10-20", "2026-11-03", "2026-11-17"]
    return [make_milestone(i, due) for i, due in enumerate(dues, start=1)]


@pytest.fixture
def bot(storage, milestones):
    return FakeBot(storage, FakeGitHub(milestones=milestones))


def contents(bot):
    return [kwargs.get("content") for _, kwargs in bot.sent]


# Deadline reminders


async def test_deadline_check_posts_once_and_records_it(monkeypatch, bot):
    freeze(monkeypatch, toronto("2026-10-17T10:00:00"))
    cog = DeadlinesCog(bot)

    assert await cog.run_check() == ["Iteration 2 (3d reminder)"]
    assert bot.sent[0][0] == REMINDERS
    assert "**Iteration 2** is due in 3 days (Tue Oct 20)" in contents(bot)[0]
    assert bot.storage.sent_reminders() == {(2, "3d")}

    assert await cog.run_check() == []  # already sent
    assert len(bot.sent) == 1


async def test_deadline_check_waits_for_reminder_hour_unless_manual(monkeypatch, bot):
    freeze(monkeypatch, toronto("2026-10-17T07:00:00"))
    cog = DeadlinesCog(bot)
    assert await cog.run_check() == []
    assert await cog.run_check(respect_hour=False) == ["Iteration 2 (3d reminder)"]


async def test_one_day_reminder_also_closes_the_three_day_one(monkeypatch, bot):
    freeze(monkeypatch, toronto("2026-10-19T10:00:00"))
    assert await DeadlinesCog(bot).run_check() == ["Iteration 2 (1d reminder)"]
    assert bot.storage.sent_reminders() == {(2, "1d"), (2, "3d")}


async def test_release_is_mentioned_on_its_last_iteration(monkeypatch, bot):
    freeze(monkeypatch, toronto("2026-11-16T10:00:00"))
    await DeadlinesCog(bot).run_check()
    assert "closes **Release 1**" in contents(bot)[0]


async def test_failed_post_is_not_recorded(monkeypatch, bot):
    freeze(monkeypatch, toronto("2026-10-17T10:00:00"))
    bot.fail_sends = True
    assert await DeadlinesCog(bot).run_check() == []
    assert bot.storage.sent_reminders() == set()


async def test_post_next_deadline_does_not_record(monkeypatch, bot):
    freeze(monkeypatch, toronto("2026-10-08T10:00:00"))
    cog = DeadlinesCog(bot)
    assert await cog.post_next() == ["Iteration 2 (due in 12 days)"]
    assert bot.storage.sent_reminders() == set()  # the scheduled reminders still go out


async def test_post_next_deadline_with_nothing_upcoming(monkeypatch, bot):
    freeze(monkeypatch, toronto("2027-01-01T10:00:00"))
    assert await DeadlinesCog(bot).post_next() == []
    assert bot.sent == []


async def test_scheduled_loop_survives_github_errors(monkeypatch, storage):
    freeze(monkeypatch, toronto("2026-10-17T10:00:00"))
    cog = DeadlinesCog(FakeBot(storage, BrokenGitHub()))
    await cog.check_deadlines.coro(cog)  # must not raise


# Meeting reminders


async def test_meeting_check_posts_due_reminders_once(monkeypatch, bot):
    now = utc("2026-10-10T12:00:00")
    freeze(monkeypatch, now)
    two_days_ago = now - timedelta(days=2)
    bot.storage.add_meeting("Planning", now + timedelta(minutes=30), None, 1, two_days_ago)
    bot.storage.add_meeting("Retro", now + timedelta(days=3), None, 1, now)
    cog = MeetingsCog(bot)

    assert await cog.run_check() == ["Planning (1h reminder)"]
    assert "**Planning** starts <t:" in contents(bot)[0]
    assert await cog.run_check() == []


async def test_post_next_meeting_does_not_record(monkeypatch, bot):
    now = utc("2026-10-10T12:00:00")
    freeze(monkeypatch, now)
    meeting = bot.storage.add_meeting("Retro", now + timedelta(days=3), None, 1, now)
    cog = MeetingsCog(bot)

    assert await cog.post_next() == ["Retro"]
    reloaded = bot.storage.get_meeting(meeting.id)
    assert not reloaded.reminded_1d and not reloaded.reminded_1h


async def test_post_next_meeting_with_none_scheduled(monkeypatch, bot):
    freeze(monkeypatch, utc("2026-10-10T12:00:00"))
    assert await MeetingsCog(bot).post_next() == []


# PR summary

NOW = utc("2026-10-10T12:00:00")


def pr(number, draft=False):
    return PullRequest(number, f"PR {number}", "dev", f"https://x/{number}", draft, NOW, ())


async def test_daily_summary_stays_quiet_without_ready_prs(monkeypatch, storage):
    freeze(monkeypatch, NOW)
    bot = FakeBot(storage, FakeGitHub(pulls=[pr(1, draft=True)]))
    assert await PRSummaryCog(bot).post_summary(skip_if_empty=True) == []
    assert bot.sent == []


async def test_manual_summary_always_posts_without_pinging(monkeypatch, storage):
    freeze(monkeypatch, NOW)
    bot = FakeBot(storage, FakeGitHub(pulls=[pr(1, draft=True)]))
    assert await PRSummaryCog(bot).post_summary(skip_if_empty=False) == ["Open PRs: none"]
    channel, kwargs = bot.sent[0]
    assert channel == SUMMARY and kwargs["content"] is None


async def test_summary_pings_role_when_prs_are_waiting(monkeypatch, storage):
    freeze(monkeypatch, NOW)
    bot = FakeBot(storage, FakeGitHub(pulls=[pr(1), pr(2)]))
    assert await PRSummaryCog(bot).post_summary(skip_if_empty=True) == [
        "Open PRs: 2 ready for review"
    ]
    assert bot.sent[0][1]["content"] == "<@&4>"


# /run commands


class FakeInteraction:
    user = "tester"

    def __init__(self):
        self.deferred_ephemeral = None
        self.replies: list[tuple[str, bool]] = []
        interaction = self

        class Response:
            async def defer(self, ephemeral=False):
                interaction.deferred_ephemeral = ephemeral

        class Followup:
            async def send(self, content=None, ephemeral=False, **kwargs):
                interaction.replies.append((content, ephemeral))

        self.response = Response()
        self.followup = Followup()


@pytest.fixture
def run_cog(bot):
    for cog in (DeadlinesCog(bot), MeetingsCog(bot), PRSummaryCog(bot)):
        bot.cogs[type(cog).__name__] = cog
    return RunCog(bot)


async def test_run_deadlines_calls_the_scheduled_job(monkeypatch, bot, run_cog):
    freeze(monkeypatch, toronto("2026-10-17T07:00:00"))  # before REMINDER_HOUR
    interaction = FakeInteraction()
    await run_cog.deadlines.callback(run_cog, interaction, False)

    assert interaction.deferred_ephemeral is True
    assert interaction.replies == [
        ("Ran deadline reminders: posted 1.\n- Iteration 2 (3d reminder)", True)
    ]
    assert bot.storage.sent_reminders() == {(2, "3d")}  # same record as a scheduled run


async def test_run_deadlines_force(monkeypatch, bot, run_cog):
    freeze(monkeypatch, toronto("2026-10-08T10:00:00"))
    interaction = FakeInteraction()
    await run_cog.deadlines.callback(run_cog, interaction, True)
    assert "Iteration 2 (due in 12 days)" in interaction.replies[0][0]


async def test_run_meeting_reminders_reports_nothing_due(monkeypatch, bot, run_cog):
    freeze(monkeypatch, utc("2026-10-10T12:00:00"))
    interaction = FakeInteraction()
    await run_cog.meeting_reminders.callback(run_cog, interaction, False)
    assert "nothing was due" in interaction.replies[0][0]
    assert "force: True" in interaction.replies[0][0]


async def test_run_pr_summary_posts_to_the_channel(monkeypatch, bot, run_cog):
    freeze(monkeypatch, NOW)
    interaction = FakeInteraction()
    await run_cog.pr_summary.callback(run_cog, interaction)
    assert bot.sent[0][0] == SUMMARY
    assert interaction.replies[0][0].startswith("Ran the PR summary: posted 1.")


async def test_run_reports_errors_instead_of_crashing(monkeypatch, storage):
    freeze(monkeypatch, toronto("2026-10-17T10:00:00"))
    bot = FakeBot(storage, BrokenGitHub())
    bot.cogs["DeadlinesCog"] = DeadlinesCog(bot)
    cog = RunCog(bot)
    monkeypatch.setattr(run_module.log, "exception", lambda *args, **kwargs: None)
    interaction = FakeInteraction()
    await cog.deadlines.callback(cog, interaction, False)
    assert interaction.replies == [
        ("Could not run deadline reminders: RuntimeError. Details are in the bot logs.", True)
    ]


def test_run_commands_have_a_cooldown(run_cog):
    for command in run_cog.run.commands:
        assert any("cooldown" in getattr(check, "__qualname__", "") for check in command.checks)
