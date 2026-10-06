from datetime import date, timedelta

from team_bot import formatting
from team_bot.domain.iterations import find_iteration, release_for
from team_bot.domain.meetings import Meeting
from team_bot.domain.worklog import MemberSummary, WorkLog
from team_bot.services.github import PullRequest

from conftest import RELEASES, make_milestone, utc

REPO = "antholim/Pulse"
NOW = utc("2026-10-10T12:00:00")


def log(id=1, name="Ana", day=date(2026, 10, 9), hours=1.5, ref=44, text="Reviewed | PR"):
    return WorkLog(id, 10 + id, name, day, text, hours, ref, NOW)


def test_small_helpers():
    assert formatting.hours(1.5) == "1.5h"
    assert formatting.hours(2.0) == "2h"
    assert formatting.issue_link(REPO, 44) == "[#44](https://github.com/antholim/Pulse/issues/44)"
    assert formatting.discord_time(utc("2026-10-14T22:30:00"), "R") == "<t:1792017000:R>"
    assert formatting.short_date(date(2026, 10, 6)) == "Tue Oct 6"
    assert formatting.truncate("abcdef", 4) == "abc…"


def test_log_confirmation(iterations):
    text = formatting.log_confirmation(log(), REPO, iterations[1])
    assert "**1.5h** on Fri Oct 9 for [#44]" in text
    assert "Iteration 2" in text and "/unlog 1" in text
    assert "no iteration" in formatting.log_confirmation(log(ref=None), REPO, None)


def test_contributions_description():
    summaries = [
        MemberSummary(1, "Ana", 4.5, 3, (21, 44)),
        MemberSummary(2, "Ben", 1, 1, ()),
    ]
    text = formatting.contributions_description(
        summaries, date(2026, 10, 7), date(2026, 10, 20), REPO
    )
    assert "**5.5h** total" in text
    assert "**1. Ana**: 4.5h (3 entries) · [#21]" in text
    assert "**2. Ben**: 1h (1 entry)" in text
    empty = formatting.contributions_description([], date(2026, 10, 7), date(2026, 10, 20), REPO)
    assert empty.startswith("No work logged")


def test_contributions_description_caps_reference_list():
    summary = MemberSummary(1, "Ana", 9, 9, tuple(range(1, 10)))
    text = formatting.contributions_description(
        [summary], date(2026, 10, 7), date(2026, 10, 20), REPO
    )
    assert "+3 more" in text


def test_deadline_message_mentions_release_on_last_iteration(iterations):
    it4 = find_iteration(4, iterations)
    text = formatting.deadline_message(it4.milestone, 3, release_for(it4, iterations, RELEASES), 4)
    assert "**Iteration 4** is due in 3 days (Tue Nov 17)" in text
    assert "closes **Release 1**" in text

    it2 = find_iteration(2, iterations)
    text2 = formatting.deadline_message(it2.milestone, 1, release_for(it2, iterations, RELEASES), 2)
    assert "due tomorrow" in text2 and "Release" not in text2
    assert "due today" in formatting.deadline_message(
        make_milestone(9, "2026-10-10"), 0, None, None
    )


def test_meeting_text():
    meeting = Meeting(3, "Planning", utc("2026-10-14T22:30:00"), "https://meet", 1, NOW)
    assert formatting.meeting_line(meeting).startswith("`#3` **Planning**: <t:1792017000:F>")
    assert "https://meet" in formatting.meeting_line(meeting)
    reminder = formatting.meeting_reminder(meeting)
    expected = "📅 Reminder: **Planning** starts <t:1792017000:R>, <t:1792017000:F>"
    assert reminder.startswith(expected)
    assert reminder.endswith("\nhttps://meet")


def test_run_result():
    assert formatting.run_result("deadline reminders", []) == (
        "Ran deadline reminders: nothing was due. Use `force: True` to post the next one anyway."
    )
    assert "force" not in formatting.run_result("the PR summary", [], force_hint=False)
    text = formatting.run_result("meeting reminders", ["Planning (1h reminder)", "Retro"])
    assert text == "Ran meeting reminders: posted 2.\n- Planning (1h reminder)\n- Retro"


def test_pr_summary_skips_drafts_and_sorts_oldest_first():
    def pr(number, age_days, draft=False, reviewers=()):
        return PullRequest(
            number,
            f"PR {number}",
            "dev",
            f"https://x/{number}",
            draft,
            NOW - timedelta(days=age_days),
            reviewers,
        )

    title, text = formatting.pr_summary(
        [pr(50, 0), pr(43, 7, reviewers=("antholim",)), pr(60, 1, draft=True)], NOW
    )
    assert title == "Open PRs: 2 ready for review"
    assert text.index("#43") < text.index("#50")
    assert "7d old · waiting on antholim" in text
    assert "today" in text
    assert "#60" not in text

    assert formatting.pr_summary([pr(60, 1, draft=True)], NOW)[0] == "Open PRs: none"


def test_contributions_markdown_groups_by_iteration(iterations):
    logs = [
        log(1, "Ana", date(2026, 10, 1)),
        log(2, "Ben", date(2026, 10, 8), hours=3, ref=None),
        log(3, "Ana", date(2027, 6, 1)),
    ]
    markdown = formatting.contributions_markdown(logs, iterations, REPO)
    assert "## Iteration 1 (2026-09-23 to 2026-10-06)" in markdown
    assert "## Iteration 2 (2026-10-07 to 2026-10-20)" in markdown
    assert "## Outside any iteration" in markdown
    assert "| Ben | 3 | 1 |" in markdown
    assert "Reviewed \\| PR" in markdown  # pipes escaped so the table does not break
    assert markdown.count("[#44]") == 2


def test_contributions_markdown_empty(iterations):
    assert "No work logged yet" in formatting.contributions_markdown([], iterations, REPO)


def test_command_usage_brackets_optional_options():
    command = formatting.CommandHelp(
        "meeting schedule", "Schedule", (("title", True), ("link", False)), "MeetingsCog"
    )
    assert formatting.command_usage(command) == "/meeting schedule title [link]"
    assert formatting.command_usage(formatting.CommandHelp("ping", "x", (), "General")) == "/ping"


def test_help_sections_order_and_unknown_cog():
    commands = [
        formatting.CommandHelp("ping", "Check the bot", (), "General"),
        formatting.CommandHelp("unlog", "Delete an entry", (("entry", True),), "WorkLogCog"),
        formatting.CommandHelp("log", "Log work", (("hours", True),), "WorkLogCog"),
        formatting.CommandHelp("mystery", "New thing", (), "SomeNewCog"),
    ]
    sections = formatting.help_sections(commands)
    assert [title for title, _ in sections] == ["Work logging", "General", "Other"]
    assert sections[0][1] == "`/log hours`\nLog work\n`/unlog entry`\nDelete an entry"


def test_help_sections_truncate_long_fields():
    many = [formatting.CommandHelp(f"c{i}", "x" * 200, (), "General") for i in range(10)]
    ((_, text),) = formatting.help_sections(many)
    assert len(text) == formatting.DISCORD_FIELD_LIMIT and text.endswith("…")


def test_automatic_posts():
    from datetime import time

    assert "every day at 21:00" in formatting.automatic_posts(time(21, 0))
    assert "turned off" in formatting.automatic_posts(None)
