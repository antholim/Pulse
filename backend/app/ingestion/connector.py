"""The interface every PULSE data source implements (ADR D6).

A connector only fetches. It yields raw records exactly as the source returned
them; archiving, normalization and storage happen later in the sync run. Omerlo,
file imports and future webhook sources all plug in through this interface.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class RawRecord:
    """One record as received from a source, before any transformation."""

    entity_kind: str
    external_id: str
    updated_at: datetime | None
    payload: dict[str, Any]
    # Set when the record only exists under another one, e.g. an event's participant.
    parent_external_id: str | None = None


class Connector(Protocol):
    kind: str

    def fetch_since(self, watermark: datetime | None) -> Iterator[RawRecord]:
        """Yield the records changed after `watermark`, or every record when it is None.

        Records without an `updated_at` are always yielded, because whether they
        changed cannot be told.
        """
        ...


def parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO 8601 timestamp as UTC-aware, returning None when missing or invalid.

    Timestamps without an offset are assumed to be UTC, so they can be compared
    with the watermark.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def is_after(record: RawRecord, watermark: datetime | None) -> bool:
    """Whether `record` belongs in a sync that starts from `watermark`."""
    return watermark is None or record.updated_at is None or record.updated_at > watermark
