# Writing PRs, issues and commits

How PULSE pull requests, issues and commit messages are written. Follow the
existing ones (for example PR #70 and PR #94, issue #57) rather than inventing a
new format. This applies to anyone writing them, people and AI tools alike.

## Commits

- One logical change per commit. Split a feature into steps that each build and
  pass the tests (for example: helper module, then the code using it, then docs).
- Short imperative sentence ending with the issue number:
  `Add security headers and configurable CORS origins (#22)`.
  An optional `feat:` / `fix:` / `test:` / `docs:` prefix is fine.
- Add a body only when the reason for the change is not obvious from the diff.
- **Never add `Co-Authored-By` trailers** or any other attribution line.

## Pull requests

Use `.github/pull_request_template.md` and keep its sections:

- **Title:** the same style as a commit message, ending with the issue number:
  `Map Omerlo payloads to normalized source records (#57)`.
- **Summary:** one or two short paragraphs on what the PR does and why, then
  `Closes #N` (one line per issue).
- **Changes:** bullets grouped by file or component, with the file in
  parentheses and a bold lead-in: `- **Client** (omerlo/client.py): ...`.
  Nested bullets for details.
- Optional sections when they help the reviewer: **Try it** (commands),
  **Decisions to review** (choices that differ from the ticket or need a second
  opinion), what is still to confirm on staging.
- **Tests:** checked boxes saying what is covered and how it was run, not only
  "tests pass".
- **Checklist:** tick only what is actually done.
- **AI assistance:** required by SOEN 490. One or two plain sentences saying
  which tool helped and with what, or "None".
- **No "Generated with ..." footer** and no `Co-Authored-By` line.

## Issues

Backlog issues are generated from `scripts/tickets/data.py` (see `CLAUDE.md`).
Hand-written ones use the templates in `.github/ISSUE_TEMPLATE/` and the same
sections as the generated tickets: Goal or User story, Context, Acceptance
criteria, Tasks, Dependencies, Out of scope, Definition of done.

## Code comments

- Short: a one-line docstring or comment, only where the code doesn't already
  say it. No multi-paragraph module docstrings explaining design decisions; those
  go in the PR description.
- **Never put issue numbers in comments or docstrings.** They belong in commit
  messages and PRs.

## Wording

Write like a teammate, not like a chatbot:

- Plain, specific sentences. Name the file, function, issue or number involved.
- No em or en dashes; use a comma, a colon, parentheses or a new sentence.
- No filler or hype: avoid "comprehensive", "robust", "seamless", "leverage",
  "delve", "ensure", "streamline", "enhance", "This PR introduces...".
- No emojis, no closing summary that repeats the bullets, no "Let me know if...".
- Don't oversell: say what was tested and what was not.
