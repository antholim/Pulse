# ai-checklist

An agent skill that checks your branch, commits and pull request against the
SOEN 490 AI-use rules, and helps you fix or backfill your own AI declarations.
The rules themselves are in `AI_USAGE.md` and `docs/writing-prs-and-issues.md`;
the skill applies them, it does not replace them.

## What it does

- Runs `scripts/ai_declarations.py` and shows which source files lack an
  `AI contribution:` line, grouped as files, commits and pull request.
- Checks your branch's commits for an AI acknowledgment line and the issue
  number, and your PR for a filled-in "AI assistance" section.
- Adds the declaration to files you mainly wrote, after asking you the level for
  each one. Files written by others are listed with their authors, not edited.
- Drafts your PR's "AI assistance" section and your `AI_USAGE.md` entries.
- Backfills declarations for your earlier merged PRs.

It never picks a level for you, never edits a PR, issue or commit message
without your yes, never rewrites pushed commits, and never adds an AI
`Co-Authored-By` line.

## Set up

The skill is in `.agents/skills/ai-checklist/SKILL.md`.

- **Claude Code** reads skills from `.claude/skills/`. Link it once from the
  repo root:

  ```bash
  mkdir -p .claude/skills && ln -s ../../.agents/skills/ai-checklist .claude/skills/ai-checklist
  ```

- **Other agents** that read `.agents/skills/` (for example Codex) pick it up
  as is. Otherwise, tell the agent to read
  `.agents/skills/ai-checklist/SKILL.md` and follow it.

You also need Python 3, `gh` signed in to GitHub, and a checkout that has
`scripts/ai_declarations.py`.

## Use it

From the repo root, on your branch, ask the agent in plain words:

| You want to | Ask |
| --- | --- |
| Check your branch before opening a PR | "Run the ai-checklist on this branch" |
| Check an open PR | "Run the ai-checklist on PR 139" |
| Declare your own files | "Fix my missing AI declarations" |
| Fill in the PR's AI section | "Fill in the AI assistance section of my PR" |
| Add your feature to `AI_USAGE.md` | "Add my feature to AI_USAGE.md" |
| Catch up on earlier work | "Backfill my AI declarations" |

In Claude Code you can also type `/ai-checklist`.

The agent asks you one question per file or PR. Answer with the level that
matches how much of the current code first came from AI:

- `No substantial AI-generated code`
- `Below 50% AI-generated`
- `50% or more AI-generated`

## Without an agent

The same checks by hand:

```bash
python3 scripts/ai_declarations.py              # files missing a declaration
python3 scripts/ai_declarations.py --report     # coverage and pending files
python3 scripts/ai_declarations.py --add below-50 backend/app/sync.py
git log --format='%h %s%n%b' origin/main..HEAD  # read each commit's AI line
```
