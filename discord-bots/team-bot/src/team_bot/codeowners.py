"""Write .github/CODEOWNERS from review-teams.toml (issue #76).

Run from discord-bots/team-bot after editing review-teams.toml:

    python -m team_bot.codeowners           # rewrite .github/CODEOWNERS
    python -m team_bot.codeowners --check   # fail if it is out of date
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from team_bot.config import ConfigError
from team_bot.domain.review_teams import load_review_teams, render_codeowners

DEFAULT_CONFIG = Path("review-teams.toml")
DEFAULT_OUTPUT = Path("../../.github/CODEOWNERS")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m team_bot.codeowners")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="Fail if it is out of date")
    args = parser.parse_args(argv)

    try:
        expected = render_codeowners(load_review_teams(args.config))
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 1
    current = args.output.read_text(encoding="utf-8") if args.output.exists() else None
    if current == expected:
        return 0
    if args.check:
        print(f"{args.output} is out of date. Run: python -m team_bot.codeowners", file=sys.stderr)
        return 1
    args.output.write_text(expected, encoding="utf-8", newline="\n")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
