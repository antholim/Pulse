import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class TenantOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str | None


class SyncRunOut(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    mode: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    counts: dict[str, Any]
    error: str | None


class ChangeOut(BaseModel):
    change_type: str
    kind: str
    source_id: uuid.UUID
    external_id: str
    label: str
    changed_fields: dict[str, Any]


class RecordOut(BaseModel):
    source_id: uuid.UUID
    external_id: str
    kind: str
    label: str
    domain: str | None
    linkedin: str | None
    valid_from: datetime


class VersionEvent(BaseModel):
    sync_run_id: uuid.UUID
    change_type: str
    changed_fields: dict[str, Any]


class VersionOut(BaseModel):
    id: uuid.UUID
    label: str
    name_normalized: str | None
    domain: str | None
    linkedin: str | None
    external_ids: dict[str, Any]
    valid_from: datetime
    valid_to: datetime | None
    first_seen_run: uuid.UUID
    removed_run: uuid.UUID | None
    events: list[VersionEvent]


class RecordHistoryOut(BaseModel):
    source_id: uuid.UUID
    external_id: str
    kind: str
    versions: list[VersionOut]
