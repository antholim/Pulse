# AI contribution: 50% or more AI-generated
"""Check that every source file declares how much of it was AI-generated.

    python scripts/ai_declarations.py                 # check (pre-commit and CI)
    python scripts/ai_declarations.py --report        # coverage and pending files
    python scripts/ai_declarations.py --add LEVEL FILE...

LEVEL is one of: none, below-50, 50-or-more.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PENDING = ROOT / "scripts" / "ai_declarations_pending.txt"

LEVELS = {
    "none": "No substantial AI-generated code",
    "below-50": "Below 50% AI-generated",
    "50-or-more": "50% or more AI-generated",
}
APPLICABLE = re.compile(
    r"^(backend/(app|synthetic|tests)/.*\.py"
    r"|frontend/src/.*\.tsx?"
    r"|discord-bots/.*\.py"
    r"|scripts/.*\.py)$"
)
EXCLUDED = {"frontend/src/vite-env.d.ts"}
DECLARATION = re.compile(
    r"^(#|//) AI contribution: (" + "|".join(re.escape(v) for v in LEVELS.values()) + r")$"
)
HEAD_LINES = 5


def applicable_files() -> list[str]:
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    return [
        path
        for path in tracked
        if APPLICABLE.match(path)
        and path not in EXCLUDED
        and (ROOT / path).is_file()
        and (ROOT / path).stat().st_size > 0
    ]


def has_declaration(path: str) -> bool:
    with (ROOT / path).open(encoding="utf-8") as file:
        head = [file.readline().rstrip("\n") for _ in range(HEAD_LINES)]
    return any(DECLARATION.match(line) for line in head)


def read_pending() -> set[str]:
    if not PENDING.exists():
        return set()
    lines = (line.strip() for line in PENDING.read_text(encoding="utf-8").splitlines())
    return {line for line in lines if line and not line.startswith("#")}


def add(level: str, paths: list[str]) -> None:
    for path in paths:
        if has_declaration(path):
            continue
        file = ROOT / path
        comment = "//" if file.suffix in {".ts", ".tsx"} else "#"
        lines = file.read_text(encoding="utf-8").splitlines(keepends=True)
        at = 1 if lines and lines[0].startswith("#!") else 0
        lines.insert(at, f"{comment} AI contribution: {LEVELS[level]}\n")
        file.write_text("".join(lines), encoding="utf-8")


def check() -> int:
    files = applicable_files()
    pending = read_pending()
    missing = [p for p in files if p not in pending and not has_declaration(p)]
    stale = sorted(p for p in pending if p not in files or has_declaration(p))
    for path in missing:
        print(f"{path}: no AI contribution declaration in the first {HEAD_LINES} lines")
    for path in stale:
        print(f"{path}: remove it from {PENDING.relative_to(ROOT)}")
    if missing or stale:
        print("Add one with: python scripts/ai_declarations.py --add LEVEL FILE (see --help)")
        return 1
    return 0


def report() -> int:
    files = applicable_files()
    declared = sum(has_declaration(p) for p in files)
    print(f"{declared}/{len(files)} source files declared ({declared / len(files):.0%})")
    for path in sorted(read_pending()):
        print(f"  pending: {path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--add", nargs="+", metavar=("LEVEL", "FILE"))
    args = parser.parse_args()
    if args.add:
        level, *paths = args.add
        if level not in LEVELS or not paths:
            parser.error(f"--add needs a level ({', '.join(LEVELS)}) and at least one file")
        add(level, paths)
        return 0
    return report() if args.report else check()


if __name__ == "__main__":
    sys.exit(main())
