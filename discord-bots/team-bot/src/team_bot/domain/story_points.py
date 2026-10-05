"""Read story points from an issue body.

Pulse issues carry a line like ``**Story points:** 5`` (written by the ticket
generator in scripts/tickets). The assignee suggestions in #45 reuse this.
"""

from __future__ import annotations

import re

STORY_POINTS = re.compile(r"\*\*\s*Story points\s*:?\s*\*\*\s*:?\s*(\d+)", re.IGNORECASE)


def parse_story_points(body: str | None) -> int | None:
    if not body:
        return None
    match = STORY_POINTS.search(body)
    return int(match.group(1)) if match else None
