"""Omerlo Reader API connector: fetches every resource PULSE needs as raw records.

Incremental strategy until #23 confirms whether an "updated since" filter
exists: every page is read and records are kept when their `updated_at` is
after the watermark. This is correct but reads everything; #23 decides how to
narrow the requests.
"""

import logging
from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import Any

import httpx

from app.ingestion.connector import RawRecord, is_after, parse_timestamp
from app.ingestion.omerlo.pagination import DEFAULT_PAGE_SIZE, paginate, read_json

logger = logging.getLogger(__name__)

API = "/api/media/v1"

# List endpoint per entity kind. Only the contents path and the event participants
# path are confirmed by the public docs; the others follow the documented pattern
# and must be verified on staging (#23).
ENDPOINTS = {
    "category": f"{API}/categories",
    "profile_type": f"{API}/profile_types",
    "organization": f"{API}/community/organizations",
    "person": f"{API}/community/people",
    "project": f"{API}/community/projects",
    "event": f"{API}/community/events",
    "content": f"{API}/contents",  # verified
}
CONTENT_DETAIL = f"{API}/contents/{{id}}"
EVENT_PARTICIPANTS = f"{API}/community/events/{{id}}/participants/people"  # verified

# Fetch order: reference data first, so later stages can resolve ids.
ENTITY_KINDS = tuple(ENDPOINTS)


class OmerloConnector:
    kind = "omerlo"

    def __init__(
        self,
        client: httpx.Client,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        entity_kinds: Sequence[str] = ENTITY_KINDS,
        content_details: bool = True,
    ):
        unknown = set(entity_kinds) - set(ENDPOINTS)
        if unknown:
            raise ValueError(f"Unknown Omerlo entity kinds: {sorted(unknown)}")
        self._client = client
        self._page_size = page_size
        self._entity_kinds = entity_kinds
        self._content_details = content_details

    def fetch_since(self, watermark: datetime | None) -> Iterator[RawRecord]:
        for kind in self._entity_kinds:
            for item in paginate(self._client, ENDPOINTS[kind], page_size=self._page_size):
                record = to_record(kind, item)
                if record is None:
                    continue
                if is_after(record, watermark):
                    if kind == "content" and self._content_details:
                        record = self._content_detail(record)
                    if record is not None:
                        yield record
                if kind == "event":
                    # Participation has no timestamp of its own and may change without
                    # the event's updated_at moving, so it is read on every sync.
                    yield from self._participants(record.external_id)

    def _content_detail(self, summary: RawRecord) -> RawRecord | None:
        """The full content, including the Profiles block linking organizations and people."""
        path = CONTENT_DETAIL.format(id=summary.external_id)
        response = self._client.get(path)
        if response.status_code == httpx.codes.NOT_FOUND:
            logger.warning("Omerlo content %s disappeared before its detail was read", path)
            return None
        response.raise_for_status()
        detail = read_json(response, path).get("data")
        if not isinstance(detail, dict):
            logger.warning("Omerlo content %s has no detail object; keeping the summary", path)
            return summary
        return to_record("content", detail) or summary

    def _participants(self, event_id: str) -> Iterator[RawRecord]:
        path = EVENT_PARTICIPANTS.format(id=event_id)
        for person in paginate(self._client, path, page_size=self._page_size):
            person_id = person.get("id")
            if person_id is None:
                logger.warning("Skipping an Omerlo participant without an id in %s", path)
                continue
            yield RawRecord(
                entity_kind="event_participant",
                external_id=f"{event_id}:{person_id}",
                updated_at=None,
                payload=person,
                parent_external_id=event_id,
            )


def to_record(kind: str, item: dict[str, Any]) -> RawRecord | None:
    """Wrap an API item as a raw record, or None (logged) when it has no id."""
    item_id = item.get("id")
    if item_id is None:
        logger.warning("Skipping an Omerlo %s without an id", kind)
        return None
    return RawRecord(
        entity_kind=kind,
        external_id=str(item_id),
        updated_at=parse_timestamp(item.get("updated_at")),
        payload=item,
    )
