"""Omerlo backoffice API connector: fetches every resource PULSE needs as raw records.

Community records (organizations, people, projects, events) are listed per
workspace. Lists return summaries only, so each changed record costs a detail
request, plus one for its metadata and, for events, one for its sessions.

The API can sort by `updated_at` but has no "updated since" filter. An incremental
sync therefore lists newest first and stops at the first record older than the
watermark; deleted records never appear in a list, so only the sync run's periodic
full sync can detect them (#55).
"""

import logging
from collections.abc import Iterator, Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any

import httpx

from app.ingestion.connector import RawRecord, is_after, parse_timestamp
from app.ingestion.omerlo.client import OmerloAPIError, OmerloNotFoundError, get_json
from app.ingestion.omerlo.pagination import DEFAULT_PAGE_SIZE, paginate

logger = logging.getLogger(__name__)

WORKSPACES = "/composer/v2/workspaces"
WORKSPACE_DETAIL = "/composer/v2/workspaces/{id}"
CATEGORIES = "/core/v2/categories"
COMMUNITY_LIST = "/community/v2/workspaces/{workspace_id}/{path}"
COMMUNITY_DETAIL = "/community/v2/{path}/{id}"
COMMUNITY_METADATA = "/community/v2/{path}/{id}/metadata"
EVENT_SESSIONS = "/community/v2/events/{id}/sessions"

# Community entity kind -> its path segment.
COMMUNITY = {
    "organization": "organizations",
    "person": "people",
    "project": "projects",
    "event": "events",
}
# Lists whose documentation includes `limit`; the others get no page size.
SIZED_LISTS = {"workspace", "category", "event"}
NEWEST_FIRST = {"sort_by": "updated_at-desc"}

# Fetch order: reference data first, so later stages can resolve ids.
ENTITY_KINDS = ("workspace", "category", *COMMUNITY)


class OmerloConnector:
    kind = "omerlo"

    def __init__(
        self,
        client: httpx.Client,
        *,
        workspace_ids: Sequence[str] | None = None,
        entity_kinds: Sequence[str] = ENTITY_KINDS,
        page_size: int = DEFAULT_PAGE_SIZE,
        metadata: bool = True,
        event_sessions: bool = True,
    ):
        """`workspace_ids` limits the sync to those workspaces; by default, every
        workspace the API key can see is synced."""
        unknown = set(entity_kinds) - set(ENTITY_KINDS)
        if unknown:
            raise ValueError(f"Unknown Omerlo entity kinds: {sorted(unknown)}")
        self._client = client
        self._workspace_ids = workspace_ids
        self._entity_kinds = entity_kinds
        self._page_size = page_size
        self._metadata = metadata
        self._event_sessions = event_sessions

    def fetch_since(self, watermark: datetime | None) -> Iterator[RawRecord]:
        workspaces = self.workspaces()
        yield from self.fetch_reference(workspaces, watermark)
        for kind in self.community_kinds:
            for workspace in workspaces:
                yield from self.fetch_community(kind, workspace["id"], watermark)

    @property
    def community_kinds(self) -> tuple[str, ...]:
        return tuple(kind for kind in COMMUNITY if kind in self._entity_kinds)

    def fetch_reference(
        self, workspaces: list[dict[str, Any]], watermark: datetime | None
    ) -> Iterator[RawRecord]:
        """The workspaces and categories changed since `watermark`."""
        if "workspace" in self._entity_kinds:
            for summary in workspaces:
                record = to_record("workspace", summary)
                if record and is_after(record, watermark):
                    yield self._workspace_detail(record)
        if "category" in self._entity_kinds:
            for item in self._list("category", CATEGORIES):
                record = to_record("category", item)
                if record and is_after(record, watermark):
                    yield record

    def _list(self, kind: str, path: str, **params: str) -> Iterator[dict[str, Any]]:
        page_size = self._page_size if kind in SIZED_LISTS else None
        return paginate(self._client, path, page_size=page_size, params=params)

    def workspaces(self) -> list[dict[str, Any]]:
        """The workspace summaries to sync."""
        workspaces = [w for w in self._list("workspace", WORKSPACES) if w.get("id")]
        if self._workspace_ids is None:
            return workspaces
        visible = {w["id"] for w in workspaces}
        missing = set(self._workspace_ids) - visible
        if missing:
            raise OmerloAPIError(f"Workspaces not visible to this API key: {sorted(missing)}")
        return [w for w in workspaces if w["id"] in self._workspace_ids]

    def _workspace_detail(self, summary: RawRecord) -> RawRecord:
        """The workspace with its statuses, which say whether a record is published."""
        body = get_json(self._client, WORKSPACE_DETAIL.format(id=summary.external_id))
        return detail_record("workspace", body) or summary

    def fetch_community(
        self, kind: str, workspace_id: str, watermark: datetime | None
    ) -> Iterator[RawRecord]:
        """One workspace's records of `kind` changed since `watermark`, newest first."""
        path = COMMUNITY_LIST.format(workspace_id=workspace_id, path=COMMUNITY[kind])
        for summary in self._list(kind, path, **NEWEST_FIRST):
            record = to_record(kind, summary)
            if record is None:
                continue
            if not is_after(record, watermark):
                break  # newest first: every remaining record is older still
            detail = self._detail(kind, record.external_id)
            if detail is None:
                continue
            yield detail
            if self._metadata:
                yield from self._record_metadata(kind, record.external_id)
            if kind == "event" and self._event_sessions:
                yield from self._sessions(record.external_id)

    def _detail(self, kind: str, record_id: str) -> RawRecord | None:
        path = COMMUNITY_DETAIL.format(path=COMMUNITY[kind], id=record_id)
        try:
            body = get_json(self._client, path)
        except OmerloNotFoundError:
            logger.warning("Omerlo %s %s disappeared before its detail was read", kind, record_id)
            return None
        record = detail_record(kind, body)
        if record is None:
            raise OmerloAPIError(f"{path}: response has no data object")
        return record

    def _record_metadata(self, kind: str, record_id: str) -> Iterator[RawRecord]:
        """The record's metadata entries, as one raw record holding the whole response."""
        path = COMMUNITY_METADATA.format(path=COMMUNITY[kind], id=record_id)
        try:
            body = get_json(self._client, path)
        except OmerloNotFoundError:
            logger.warning("Omerlo %s %s disappeared before its metadata was read", kind, record_id)
            return
        yield RawRecord(
            entity_kind=f"{kind}_metadata",
            external_id=record_id,
            updated_at=None,
            payload=body,
            parent_external_id=record_id,
        )

    def _sessions(self, event_id: str) -> Iterator[RawRecord]:
        """The event's current sessions.

        They are a complete replacement set: a session removed from the event simply
        stops appearing, so the sync run must compare against the previous set.
        """
        path = EVENT_SESSIONS.format(id=event_id)
        try:
            sessions = get_json(self._client, path).get("data")
        except OmerloNotFoundError:
            logger.warning("Omerlo event %s disappeared before its sessions were read", event_id)
            return
        if not isinstance(sessions, list):
            raise OmerloAPIError(f"{path}: response has no data list")
        for session in sessions:
            record = to_record("event_session", session)
            if record is not None:
                yield replace(record, parent_external_id=event_id)


def detail_record(kind: str, body: dict[str, Any]) -> RawRecord | None:
    data = body.get("data")
    return to_record(kind, data) if isinstance(data, dict) else None


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
