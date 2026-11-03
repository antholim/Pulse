---
name: ai-checklist
description: Use when the user asks to check a PULSE branch, commits, or pull request against the SOEN 490 AI-use rules, to add or fix AI-contribution declarations, to fill in a pull request's AI assistance section or AI_USAGE.md, or to backfill their own declarations for earlier work.
---

# Check and fix AI-use declarations

PULSE's AI-use rules are in `AI_USAGE.md` under "How we declare AI contribution" and in `docs/writing-prs-and-issues.md` (commits, pull requests, issues). The rubric behind them is section 8 of the SOEN 490 Code Quality Rubric. Read both files before starting; when this skill disagrees with them, they win.

## Ground rules

- **Only the user's own AI use.** Never guess another contributor's AI usage or choose a level for a file the user did not write. Report those files and name the author from git history instead.
- **The user chooses each level.** Levels are good-faith estimates of how much of the current implementation originated from AI. Student edits do not erase that origin. You may share evidence, such as the commit's AI acknowledgment, but the user decides.
- **Nothing outside the working tree changes without a yes.** Show the exact text before editing a pull request description, an issue, or a commit message. Never rewrite pushed commits or force-push.
- **No `Co-Authored-By` trailer for AI tools** and no "Generated with ..." footer, in commits or pull requests.

## 1. Run the check

From the repository root:

```bash
python3 scripts/ai_declarations.py              # every applicable source file (pre-commit and CI)
python3 scripts/ai_declarations.py --report     # coverage and the pending files
git log --format='%h %s%n%b' origin/main..HEAD  # commits on this branch
gh pr view --json number,body                   # the branch's pull request, if any
```

The script checks that each source file has an `AI contribution:` line with one of the three exact levels in its first five lines. It covers Python in `backend/app`, `backend/synthetic`, `backend/tests`, `discord-bots` and `scripts`, and TypeScript in `frontend/src`. Alembic migrations, empty files and `vite-env.d.ts` are skipped. Files still waiting for their author's estimate are listed in `scripts/ai_declarations_pending.txt`.

Check by hand:

- **Commits:** an AI-use acknowledgment line when an AI tool helped, and the issue number such as `(#134)` at the end of the subject.
- **Pull request:** the "AI assistance" section filled in, with exactly one level, the AI-assisted files, and one sentence saying which tool helped and with what. A PR that used no AI says "None".

Show the user the result grouped as files, commits, and pull request.

## 2. Fix source files

For each failing or pending file:

1. Find who wrote it: `git log --format='%an' -- <path> | sort | uniq -c` and, for shared files, `git blame --line-porcelain <path> | grep '^author ' | sort | uniq -c`.
2. If it is not mainly the user's file, list it under "Other authors" with the names, and do not edit it.
3. If it is, ask the user which level applies, one file at a time (with buttons if your environment has them). Then add the line and remove the file from the pending list:

   ```bash
   python3 scripts/ai_declarations.py --add <none|below-50|50-or-more> <path>
   ```

   This puts the line at the top, in the file's comment syntax (`#` for Python, `//` for TypeScript):

   ```python
   # AI contribution: Below 50% AI-generated
   ```

Run the check again afterwards.

## 3. Fix commits

A commit without an acknowledgment cannot be fixed after it is pushed. Report it, and make sure the pull request's acknowledgment covers that work. For an unpushed commit, offer to reword it, and do so only after the user agrees. Follow the user's own instructions for the acknowledgment's wording; otherwise use the trailer from `docs/writing-prs-and-issues.md`, naming the tool and what it contributed, for example `AI-assisted: Claude Code helped write the tests.`

## 4. Fill in the pull request section

Draft the "AI assistance" section of `.github/pull_request_template.md`:

- **AI contribution:** the level for the implementation the PR introduces or substantially changes. Base it on the user's file levels; do not pick a lower level than the files support.
- **AI-assisted files:** every changed file whose level is not `No substantial AI-generated code`.
- **Verification:** the tests that exercise those files, found by reading them, and any substantive review comments. Do not claim tests ran unless they did.

Show the full updated description, then update it with `gh pr edit <number> --body-file <file>` only after the user agrees.

## 5. Update AI_USAGE.md

When the PR implements a substantive feature with substantial AI assistance:

- Add the feature to the "Features built with substantial AI help" table, with its issues and PRs.
- Offer to add a section under "Details" in the same shape as the existing ones. Ask the user what AI got wrong and which suggestions they rejected; record "None found" only if they say so.
- Add any new tool, or the user as a new user of a tool, to the "Tools" table.

## Backfill earlier work

When the user wants to catch up on earlier declarations:

1. Run the check with `--report` and keep the pending files the user mainly wrote (step 2). Go through them in small batches, asking the level for each, and commit them on a branch for the backfill issue.
2. Find the user's merged pull requests: `gh pr list --author @me --state merged --limit 100 --json number,title,body,headRefName`. For each feature or bug PR whose description lacks the AI assistance section, draft it as in step 4. Edit each PR only after the user agrees to that PR's text.
3. Draft `AI_USAGE.md` entries for the user's features as in step 5.

Finish with a summary: files declared, files left for other authors, PRs updated, and anything the user chose to skip.
