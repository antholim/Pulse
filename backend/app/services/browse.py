"""Read-only queries behind the sync runs page. Every query is scoped to one tenant."""

import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models import RecordChange, SourceRecord, SyncRun, Tenant

RUN_LIMIT = 50
SEARCH_LIMIT = 50


def label(record: SourceRecord) -> str:
    """A display name read from the stored payload, falling back to the normalized name."""
    attributes = record.attributes or {}
    if record.kind == "organization" and attributes.get("name"):
        return attributes["name"]
    if record.kind == "person":
        name = " ".join(p for p in (attributes.get("first_name"), attributes.get("last_name")) if p)
        if name:
            return name
    for locale in attributes.get("locales") or []:
        if isinstance(locale, dict) and locale.get("name"):
            return locale["name"]
    return record.name_normalized or record.external_id


def list_tenants(session: Session) -> list[Tenant]:
    return list(session.scalars(select(Tenant).order_by(Tenant.name)))


def get_tenant(session: Session, tenant_id: uuid.UUID) -> Tenant:
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        raise NotFoundError("Tenant not found")
    return tenant


def list_runs(session: Session, tenant_id: uuid.UUID, limit: int = RUN_LIMIT) -> list[SyncRun]:
    statement = (
        select(SyncRun)
        .where(SyncRun.tenant_id == tenant_id)
        .order_by(SyncRun.started_at.desc())
        .limit(limit)
    )
    return list(session.scalars(statement))


def run_changes(
    session: Session, tenant_id: uuid.UUID, run_id: uuid.UUID
) -> list[tuple[RecordChange, SourceRecord]]:
    run = session.scalar(
        select(SyncRun).where(SyncRun.tenant_id == tenant_id, SyncRun.id == run_id)
    )
    if run is None:
        raise NotFoundError("Sync run not found")
    statement = (
        select(RecordChange, SourceRecord)
        .join(
            SourceRecord,
            (SourceRecord.tenant_id == RecordChange.tenant_id)
            & (SourceRecord.id == RecordChange.source_record_id),
        )
        .where(RecordChange.tenant_id == tenant_id, RecordChange.sync_run_id == run_id)
    )
    rows = [(change, record) for change, record in session.execute(statement)]
    return sorted(rows, key=lambda row: (row[0].change_type, row[1].kind, label(row[1]).lower()))


def search_records(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    kind: str | None = None,
    query: str | None = None,
    limit: int = SEARCH_LIMIT,
) -> list[SourceRecord]:
    """Current versions, matched on the normalized or the stored name."""
    statement = select(SourceRecord).where(
        SourceRecord.tenant_id == tenant_id, SourceRecord.valid_to.is_(None)
    )
    if kind:
        statement = statement.where(SourceRecord.kind == kind)
    if query:
        pattern = f"%{query.strip()}%"
        statement = statement.where(
            or_(
                SourceRecord.name_normalized.ilike(pattern),
                SourceRecord.attributes["name"].astext.ilike(pattern),
                SourceRecord.external_id == query.strip(),
            )
        )
    statement = statement.order_by(SourceRecord.name_normalized).limit(limit)
    return list(session.scalars(statement))


def record_history(
    session: Session, tenant_id: uuid.UUID, source_id: uuid.UUID, external_id: str
) -> tuple[list[SourceRecord], dict[uuid.UUID, list[RecordChange]]]:
    """Every version of one record, oldest first, with the changes that point at each."""
    versions = list(
        session.scalars(
            select(SourceRecord)
            .where(
                SourceRecord.tenant_id == tenant_id,
                SourceRecord.source_id == source_id,
                SourceRecord.external_id == external_id,
            )
            .order_by(SourceRecord.valid_from)
        )
    )
    if not versions:
        raise NotFoundError("Record not found")
    changes = session.scalars(
        select(RecordChange).where(
            RecordChange.tenant_id == tenant_id,
            RecordChange.source_record_id.in_([v.id for v in versions]),
        )
    )
    by_version: dict[uuid.UUID, list[RecordChange]] = defaultdict(list)
    for change in changes:
        by_version[change.source_record_id].append(change)
    return versions, by_version


def run_order(session: Session, run_ids: set[uuid.UUID]) -> dict[uuid.UUID, Any]:
    """Start time of each run, to order a version's events."""
    if not run_ids:
        return {}
    rows = session.execute(select(SyncRun.id, SyncRun.started_at).where(SyncRun.id.in_(run_ids)))
    return dict(rows.tuples())
