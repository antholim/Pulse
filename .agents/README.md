# Agent skills

Shared skills for AI agents, one folder each under `skills/`.

## ai-checklist

`skills/ai-checklist/SKILL.md` is an agent skill that checks your branch, commits and pull request against the
SOEN 490 AI-use rules (`docs/AI_USAGE.md` and `docs/writing-prs-and-issues.md`), and
helps you add your own AI declarations.

It only declares files you wrote, asks you the level for each one, and changes
nothing on GitHub without your yes.

### Before you start

You need Python 3, the GitHub CLI signed in (`gh auth status`), and Claude Code.

Your branch must contain `scripts/ai_declarations.py` and `docs/AI_USAGE.md`,
so update it from `main` first if it is older.

On Windows, type `python` where these steps say `python3`.

### Steps

1. **Go to the repo root and switch to your branch.**

   ```bash
   cd Pulse
   git checkout <your-branch>
   git pull
   ```

2. **Link the skill so Claude Code finds it** (once per clone).

   ```bash
   mkdir -p .claude/skills
   ln -s ../../.agents/skills/ai-checklist .claude/skills/ai-checklist
   ```

   On Windows (PowerShell), use a junction instead, which needs no admin rights:

   ```powershell
   New-Item -ItemType Directory -Force .claude\skills
   cmd /c mklink /J .claude\skills\ai-checklist .agents\skills\ai-checklist
   ```

   The link is in `.gitignore`, so it is never committed.

3. **Start Claude Code and run the skill.**

   ```bash
   claude
   ```

   Then type `/ai-checklist`, or ask "Run the ai-checklist on this branch". For
   an open pull request, add its number: "Run the ai-checklist on PR 139".

4. **Read the report.** It lists problems in three groups:
   - **Files:** source files with no `AI contribution:` line.
   - **Commits:** commits with no AI acknowledgment line or issue number.
   - **Pull request:** a missing or incomplete "AI assistance" section.

5. **Answer one question per file you wrote.** Pick the level that matches how
   much of the current code first came from AI:
   - `No substantial AI-generated code`
   - `Below 50% AI-generated`
   - `50% or more AI-generated`

   The agent adds the line to the top of the file and removes the file from
   `scripts/ai_declarations_pending.txt`. Files written by someone
   else are listed with their author's name; tell that person, do not declare
   them yourself.

6. **Approve the pull request text.** The agent shows the "AI assistance"
   section it drafted. Say yes to post it, or tell it what to change.

7. **Add your feature to `docs/AI_USAGE.md`** if AI helped substantially. The agent
   asks what the AI got wrong and what you rejected, and drafts the entry.

8. **Commit and push.** End the commit with your AI acknowledgment line and no
   AI `Co-Authored-By` line, then run the check again:

   ```bash
   python3 scripts/ai_declarations.py
   ```

   No output and exit code 0 means every file is declared.

### Catch up on earlier work

Ask "Backfill my AI declarations". The agent goes through the files still
waiting on you and your earlier merged PRs, one batch at a time, with the same
questions as steps 5 and 6.

### Without Claude Code

Other agents: tell them to read `.agents/skills/ai-checklist/SKILL.md` and
follow it. Or do it by hand:

```bash
python3 scripts/ai_declarations.py                                # files missing a declaration
python3 scripts/ai_declarations.py --report                       # coverage and pending files
python3 scripts/ai_declarations.py --add below-50 <file>          # declare one of your files
# then delete that file's line from scripts/ai_declarations_pending.txt, or the check fails
git log --format='%h %s%n%b' origin/main..HEAD                    # check each commit's AI line
```
