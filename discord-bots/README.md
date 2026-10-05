# Discord bots

Internal tooling for the team's Discord server. Nothing in this folder is part of the PULSE
product, and PULSE code must not import from it.

| Bot | What it does |
| --- | --- |
| [team-bot](team-bot/) | Work logging (`/log`, `/contributions`), iteration deadline and meeting reminders, daily open PR summary (#44) |

Each bot is a self-contained project with its own dependencies, tests and README. Its CI
runs only when files in its folder change.
