# AI contribution: 50% or more AI-generated
"""Check that a pull request description fills in its "AI assistance" section.

PR_BODY="$(gh pr view 145 --json body --jq .body)" python scripts/pr_ai_assistance.py
"""

import os
import re
import sys

from ai_declarations import LEVELS

SECTION = re.compile(r"^##\s*AI assistance\s*$", re.IGNORECASE | re.MULTILINE)
NEXT_SECTION = re.compile(r"^##\s", re.MULTILINE)
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
LEVEL_LINE = re.compile(r"^\W*AI contribution:(.*)$", re.IGNORECASE | re.MULTILINE)
FILES_LINE = re.compile(r"^\W*AI-assisted files:", re.IGNORECASE)
BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
DECORATION = "*` \t"

NO_SECTION = 'The PR description has no "## AI assistance" section.'
BAD_LEVEL = f'"AI contribution:" must be exactly one of: {", ".join(LEVELS.values())}.'
NO_FILES = 'List at least one file under "AI-assisted files:".'


def ai_section(body: str) -> str | None:
    text = COMMENT.sub("", body.replace("\r\n", "\n"))
    start = SECTION.search(text)
    if start is None:
        return None
    rest = text[start.end() :]
    end = NEXT_SECTION.search(rest)
    return rest[: end.start()] if end else rest


def listed_files(section: str) -> list[str]:
    lines = section.splitlines()
    start = next((i for i, line in enumerate(lines) if FILES_LINE.match(line)), None)
    if start is None:
        return []
    files = []
    for line in lines[start + 1 :]:
        bullet = BULLET.match(line)
        if bullet is None:
            if line.strip():
                break
            continue
        name = bullet.group(1).strip(DECORATION)
        if name:
            files.append(name)
    return files


def problems(body: str | None) -> list[str]:
    section = ai_section(body or "")
    if section is None:
        return [NO_SECTION]
    level = LEVEL_LINE.search(section)
    value = level.group(1).strip(DECORATION) if level else ""
    if value not in LEVELS.values():
        return [BAD_LEVEL]
    if value != LEVELS["none"] and not listed_files(section):
        return [NO_FILES]
    return []


def main() -> int:
    found = problems(os.environ.get("PR_BODY"))
    for problem in found:
        print(problem)
    if found:
        print("See the AI assistance part of docs/writing-prs-and-issues.md.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
