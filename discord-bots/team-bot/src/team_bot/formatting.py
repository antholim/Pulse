"""Text for Discord messages and the wiki export. Pure functions, no Discord calls."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time

from team_bot.domain.iterations import Iteration, Milestone, ReleaseWindow
from team_bot.domain.meetings import Meeting
from team_bot.domain.worklog import MemberSummary, WorkLog, summarize
from team_bot.services.github import PullRequest

DISCORD_DESCRIPTION_LIMIT = 4096
DISCORD_FIELD_LIMIT = 1024

# /help sections, in display order, keyed by the cog class that owns the commands.
HELP_SECTIONS = {
    "WorkLogCog": "Work logging",
    "MeetingsCog": "Meetings",
    "PRSummaryCog": "GitHub",
    "RunCog": "Run a scheduled job now",
    "General": "General",
}
OTHER_SECTION = "Other"


@dataclass(frozen=True)
class CommandHelp:
    name: str  # qualified name, e.g. "meeting schedule"
    description: str
    params: tuple[tuple[str, bool], ...]  # (name, required)
    cog: str  # class name of the cog that owns the command


def command_usage(command: CommandHelp) -> str:
    """`/log description hours [issue] [day]`: optional options in brackets."""
    parts = [f"/{command.name}"]
    parts += [name if required else f"[{name}]" for name, required in command.params]
    return " ".join(parts)


def help_sections(commands: Sequence[CommandHelp]) -> list[tuple[str, str]]:
    """Group commands into (section title, text) pairs in HELP_SECTIONS order."""
    grouped: dict[str, list[CommandHelp]] = {}
    for command in commands:
        grouped.setdefault(HELP_SECTIONS.get(command.cog, OTHER_SECTION), []).append(command)

    order = [*HELP_SECTIONS.values(), OTHER_SECTION]
    sections = []
    for title in order:
        if title not in grouped:
            continue
        lines = [
            f"`{command_usage(c)}`\n{c.description}"
            for c in sorted(grouped[title], key=lambda c: c.name)
        ]
        sections.append((title, truncate("\n".join(lines), DISCORD_FIELD_LIMIT)))
    return sections


def automatic_posts(pr_summary_time: time | None) -> str:
    lines = [
        "- Deadline reminders 3 days and 1 day before each milestone",
        "- Meeting reminders 1 day and 1 hour before",
    ]
    if pr_summary_time is None:
        lines.append("- Daily open PR summary: turned off")
    else:
        lines.append(
            f"- Open PR summary every day at {pr_summary_time:%H:%M}, when PRs are waiting"
        )
    return "\n".join(lines)


def hours(value: float) -> str:
    return f"{value:g}h"


def discord_time(moment: datetime, style: str = "F") -> str:
    """Discord renders <t:...> in each reader's own timezone."""
    return f"<t:{int(moment.timestamp())}:{style}>"


def issue_link(repo: str, number: int) -> str:
    # /issues/N redirects to /pull/N for pull requests, so one URL works for both.
    return f"[#{number}](https://github.com/{repo}/issues/{number})"


def short_date(day: date) -> str:
    return f"{day:%a %b} {day.day}"


def truncate(text: str, limit: int = DISCORD_DESCRIPTION_LIMIT) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def log_confirmation(log: WorkLog, repo: str, iteration: Iteration | None) -> str:
    parts = [f"Logged **{hours(log.hours)}** on {short_date(log.work_date)}"]
    if log.reference is not None:
        parts.append(f"for {issue_link(repo, log.reference)}")
    text = " ".join(parts) + f": {log.description}"
    where = f"{iteration.title}" if iteration else "no iteration"
    return f"{text}\nEntry `#{log.id}` · {where} · undo with `/unlog {log.id}`"


def contributions_description(
    summaries: Sequence[MemberSummary], start: date, end: date, repo: str
) -> str:
    if not summaries:
        return f"No work logged between {short_date(start)} and {short_date(end)}."
    total = sum(s.hours for s in summaries)
    lines = [f"{short_date(start)} to {short_date(end)} · **{hours(round(total, 2))}** total", ""]
    for rank, summary in enumerate(summaries, start=1):
        refs = ", ".join(issue_link(repo, n) for n in summary.references[:6])
        if len(summary.references) > 6:
            refs += f" +{len(summary.references) - 6} more"
        entry_word = "entry" if summary.entries == 1 else "entries"
        line = (
            f"**{rank}. {summary.member_name}**: {hours(summary.hours)} "
            f"({summary.entries} {entry_word})"
        )
        if refs:
            line += f" · {refs}"
        lines.append(line)
    return truncate("\n".join(lines))


def deadline_message(
    milestone: Milestone,
    days_left: int,
    release: ReleaseWindow | None,
    iteration_number: int | None,
) -> str:
    assert milestone.due_date is not None
    when = {0: "today", 1: "tomorrow"}.get(days_left, f"in {days_left} days")
    text = f"⏰ **{milestone.title}** is due {when} ({short_date(milestone.due_date)})."
    if release and iteration_number == release.last_iteration:
        text += f" This also closes **{release.name}**."
    if milestone.html_url:
        text += f"\nOpen items: {milestone.html_url}"
    return text


def meeting_line(meeting: Meeting) -> str:
    line = f"`#{meeting.id}` **{meeting.title}**: {discord_time(meeting.starts_at)}"
    line += f" ({discord_time(meeting.starts_at, 'R')})"
    if meeting.link:
        line += f" · {meeting.link}"
    return line


def meeting_reminder(meeting: Meeting) -> str:
    # The relative timestamp ("in 23 hours", "in 58 minutes") is rendered by Discord, so the
    # same text is right for the scheduled 1d/1h reminders and for a manual /run.
    text = (
        f"📅 Reminder: **{meeting.title}** starts {discord_time(meeting.starts_at, 'R')}, "
        f"{discord_time(meeting.starts_at)}."
    )
    if meeting.link:
        text += f"\n{meeting.link}"
    return text


def run_result(job: str, posted: Sequence[str], force_hint: bool = True) -> str:
    """Reply to a /run command, saying what was posted."""
    if not posted:
        text = f"Ran {job}: nothing was due."
        if force_hint:
            text += " Use `force: True` to post the next one anyway."
        return text
    return f"Ran {job}: posted {len(posted)}.\n" + "\n".join(f"- {item}" for item in posted)


def pr_summary(prs: Sequence[PullRequest], now: datetime) -> tuple[str, str]:
    """Return (title, description) for the daily open PR summary embed."""
    ready = sorted((pr for pr in prs if not pr.draft), key=lambda pr: pr.created_at)
    if not ready:
        return "Open PRs: none", "No pull requests are waiting for review. 🎉"
    lines = []
    for pr in ready:
        age = (now - pr.created_at).days
        age_text = "today" if age == 0 else f"{age}d old"
        line = f"**[#{pr.number}: {pr.title}]({pr.html_url})**\nby {pr.author} · {age_text}"
        if pr.requested_reviewers:
            line += " · waiting on " + ", ".join(pr.requested_reviewers)
        lines.append(line)
    return f"Open PRs: {len(ready)} ready for review", truncate("\n\n".join(lines))


def _md_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def contributions_markdown(
    logs: Sequence[WorkLog], iterations: Sequence[Iteration], repo: str
) -> str:
    """Markdown for the wiki: per-iteration totals followed by every entry."""
    out = ["# Team contributions", ""]
    remaining = list(logs)
    groups: list[tuple[str, list[WorkLog]]] = []
    for iteration in iterations:
        members = [log for log in remaining if iteration.contains(log.work_date)]
        if members:
            label = f"{iteration.title} ({iteration.start} to {iteration.end})"
            groups.append((label, members))
            grouped_ids = {log.id for log in members}
            remaining = [log for log in remaining if log.id not in grouped_ids]
    if remaining:
        groups.append(("Outside any iteration", remaining))

    if not groups:
        return "# Team contributions\n\nNo work logged yet.\n"

    for label, group in groups:
        out += [f"## {label}", "", "| Member | Hours | Entries |", "| --- | ---: | ---: |"]
        for summary in summarize(group):
            out.append(
                f"| {_md_cell(summary.member_name)} | {summary.hours:g} | {summary.entries} |"
            )
        out += [
            "",
            "| Date | Member | Hours | Issue/PR | Description |",
            "| --- | --- | ---: | --- | --- |",
        ]
        for log in group:
            ref = (
                f"[#{log.reference}](https://github.com/{repo}/issues/{log.reference})"
                if log.reference is not None
                else ""
            )
            out.append(
                f"| {log.work_date} | {_md_cell(log.member_name)} | {log.hours:g} | {ref} "
                f"| {_md_cell(log.description)} |"
            )
        out.append("")
    return "\n".join(out)
