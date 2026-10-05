# Team bot

Internal Discord bot for the PULSE team (issue #44). It logs who worked on what,
reminds everyone of iteration deadlines and meetings, and posts a daily summary of
open pull requests. This is team tooling, not part of the PULSE product.

## Commands

| Command | What it does |
| --- | --- |
| `/log description hours [issue] [day]` | Record work you did. `issue` is an issue or PR number, `day` is `YYYY-MM-DD` (defaults to today). Only you see the confirmation. |
| `/unlog entry` | Delete one of your own entries (the number is shown when you log). |
| `/contributions [period] [member] [export]` | Hours per member for the current `iteration` (default), the current `release`, or `all`. `export: True` attaches a markdown file you can paste into the wiki. |
| `/meeting schedule title date time [link]` | Schedule a meeting. `date` is `YYYY-MM-DD`, `time` is `HH:MM` in team time (America/Toronto). Reminders are posted 1 day and 1 hour before. |
| `/meeting list` | Upcoming meetings, shown in each reader's own timezone. |
| `/meeting cancel meeting_id` | Cancel a meeting you scheduled (server managers can cancel any). |
| `/prs` | Open pull requests waiting for review (only you see it). |
| `/run deadlines [force]` | Run the deadline reminder job now. |
| `/run meeting-reminders [force]` | Run the meeting reminder job now. |
| `/run pr-summary` | Post the open PR summary to the channel now. |
| `/ping` | Check the bot is online. |

Automatic posts, all in the reminders channel unless configured otherwise:

- **Deadline reminders** for every open milestone with a due date, 3 days and 1 day before.
  When an iteration also closes a release (Iteration 4 closes Release 1), the reminder says so.
- **Meeting reminders** 1 day and 1 hour before. The 1-day reminder is skipped for meetings
  scheduled less than a day ahead.
- **Daily open PR summary** at `PR_SUMMARY_TIME` (21:00 by default). Nothing is posted when no
  PR is waiting.

### Running a scheduled job by hand

Every automatic post has a `/run` command that calls the exact same code as the schedule,
so it posts the same messages and records the same "already sent" state. Only the person
who ran it sees the reply, which lists what was posted.

| Command | Same as the schedule, except | `force: True` |
| --- | --- | --- |
| `/run deadlines` | Ignores `REMINDER_HOUR` | Posts a reminder for the next deadline even if it is not due yet |
| `/run meeting-reminders` | Nothing different | Reminds everyone of the next meeting even if it is not due yet |
| `/run pr-summary` | Posts even when no PR is waiting (without pinging the role) | (no option) |

A forced reminder is not recorded as sent, so the regular 3-day / 1-day and 1-day / 1-hour
reminders still go out. Each `/run` job can be used once every 30 seconds per server.

Example: on Oct 17 at 8:00 (before `REMINDER_HOUR`), `/run deadlines` posts the
"Iteration 2 is due in 3 days" reminder right away, and the scheduled check later that
day posts nothing because it is already recorded.

GitHub activity itself (new issues, PRs, reviews, merges) is posted by GitHub's built-in
Discord webhook, not by this bot. See [GitHub notifications](#github-notifications).

## How iterations and releases are worked out

The bot reads the `Iteration N` milestones from GitHub. Iteration N covers the days after
Iteration N-1's due date, up to and including its own due date. Iteration 1 starts 14 days
before it is due. For example, with Iteration 1 due Oct 6 and Iteration 2 due Oct 20,
work logged on Oct 7 counts toward Iteration 2.

Releases come from the `RELEASES` setting (`Release 1=4,Release 2=8,Final Release=13`, which
matches `scripts/tickets/data.py`). A release spans from the start of its first iteration to
the due date of its last.

Moving a milestone's due date on GitHub moves the iteration with it. Work logs only store the
date, so totals always follow the current milestones.

## Setup

### 1. Create the Discord bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and click
   **New Application**.
2. Under **Bot**, click **Reset Token** and copy it into `DISCORD_TOKEN`. No privileged
   intents are needed, leave them off.
3. Under **OAuth2 > URL Generator**, tick the scopes `bot` and `applications.commands`, then
   the permissions **View Channels**, **Send Messages**, **Embed Links** and **Attach Files**.
   Open the generated URL and add the bot to the team server.
4. In Discord, turn on **Settings > Advanced > Developer Mode**. Right-click the server and
   the reminders channel and use **Copy ID** for `DISCORD_GUILD_ID` and `REMINDERS_CHANNEL_ID`.

### 2. Give it read access to GitHub

Pick one:

- **Fine-grained personal access token** (simplest). Create one at
  <https://github.com/settings/personal-access-tokens> with access to this repository only and
  the permissions **Issues: Read** and **Pull requests: Read**. Put it in `GITHUB_TOKEN`.
- **GitHub App** (not tied to one person's account). Create an app with the same two read
  permissions, install it on the repository, generate a private key, and fill in
  `GITHUB_APP_ID`, `GITHUB_INSTALLATION_ID` (the number at the end of the installation URL)
  and `GITHUB_PRIVATE_KEY` or `GITHUB_PRIVATE_KEY_PATH`.

Assignee suggestions (#45) will need write access to issues later.

### 3. Run it

Requires Python 3.12 or newer (`python --version`).

```bash
cd discord-bots/team-bot
python -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cp .env.example .env             # then fill it in (PowerShell: copy .env.example .env)
python -m team_bot
```

The bot creates its SQLite database at `DB_PATH` (default `data/team-bot.db`) on first start.
Slash commands appear in the server right after start-up.

With Docker:

```bash
docker build -t team-bot .
docker run -d --name team-bot --restart unless-stopped \
  --env-file .env -v team-bot-data:/data team-bot
```

### 4. Hosting

The bot only makes outgoing connections, so it does not need a public URL or open port.
It does need a disk that persists between restarts for the SQLite file. A teammate's
always-on machine or a small free VM both work. Back up the `.db` file now and then (it is a
single file, copying it is enough).

## GitHub notifications

This uses GitHub's built-in Discord support, no code involved. It needs admin access to the
repository.

1. In Discord, open the channel settings for the notifications channel, go to
   **Integrations > Webhooks > New Webhook**, and copy the webhook URL.
2. On GitHub, go to **Settings > Webhooks > Add webhook** for the repository.
3. **Payload URL**: the Discord webhook URL with `/github` added at the end.
   **Content type**: `application/json`.
4. Choose **Let me select individual events** and tick **Issues**, **Pull requests** and
   **Pull request reviews**. Save.

## Configuration

All settings are environment variables. See [.env.example](.env.example) for the full list.

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `DISCORD_TOKEN` | yes | | Bot token |
| `DISCORD_GUILD_ID` | yes | | Server ID, commands are synced there |
| `REMINDERS_CHANNEL_ID` | yes | | Deadline and meeting reminders |
| `GITHUB_REPO` | yes | | `owner/name` |
| `GITHUB_TOKEN` or the `GITHUB_APP_*` trio | yes | | See step 2 |
| `PR_SUMMARY_CHANNEL_ID` | no | reminders channel | |
| `PR_SUMMARY_TIME` | no | `21:00` | Empty turns the daily summary off |
| `PR_SUMMARY_ROLE_ID` | no | | Role pinged by the daily summary |
| `TIMEZONE` | no | `America/Toronto` | Used for meeting input and posting times |
| `REMINDER_HOUR` | no | `9` | Deadline reminders wait until this hour |
| `DB_PATH` | no | `data/team-bot.db` | |
| `RELEASES` | no | `Release 1=4,Release 2=8,Final Release=13` | Release name = last iteration |

The bot never mentions `@everyone` or `@here`.

## Development

```bash
pip install -e ".[dev]"
pytest --cov           # unit tests and coverage
ruff check . && ruff format --check .
```

Layout:

```
src/team_bot/
  __main__.py        entry point (python -m team_bot)
  config.py          environment variables
  bot.py             Discord client, loads the cogs, syncs slash commands
  formatting.py      message and markdown text (pure functions)
  cogs/              slash commands and scheduled jobs, kept thin
    run.py           /run group: triggers the jobs in deadlines, meetings, pr_summary
  domain/            iterations, work log summaries, reminder timing, story points
  services/          SQLite storage and the GitHub client
tests/               pytest suite, GitHub is faked and SQLite runs in memory
```

Logic lives in `domain/`, `services/` and `formatting.py` so it can be tested without
Discord. The cogs only read options, call that logic and send the result.

Each scheduled job is a method on its cog (`DeadlinesCog.run_check`, `MeetingsCog.run_check`,
`PRSummaryCog.post_summary`) that returns what it posted. The `tasks.loop` and the matching
`/run` command both call that method, and `tests/test_jobs.py` tests it with a fake bot and
a frozen clock. Coverage leaves out `bot.py`, `general.py` and `worklog.py`, which only
handle Discord interactions; `tests/test_bot_commands.py` still loads every cog and checks
the command tree.

To add a command, create a cog in `cogs/` with an async `setup(bot)` function and add its
module path to `EXTENSIONS` in `bot.py`. To add a scheduled job, put its body in a method
that returns a list of what it posted, call it from the loop, and add a `/run` subcommand
in `cogs/run.py`.

## Credits

The daily open PR summary is based on the one in last year's JavaScript bot, a fork of
[OriginalByteMe/Discord-PR-bot](https://github.com/OriginalByteMe/Discord-PR-bot)
(MIT licence, Noah Rijkaard). It was rewritten in Python here.
