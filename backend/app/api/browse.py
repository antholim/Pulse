"""Read-only endpoints for the sync runs page: runs, their changes and record history."""

import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.database import DatabaseNotConfiguredError, get_db
from app.core.errors import DatabaseUnavailableError
from app.models.records import ENTITY_KINDS
from app.schemas.browse import (
    ChangeOut,
    RecordHistoryOut,
    RecordOut,
    SyncRunOut,
    TenantOut,
    VersionEvent,
    VersionOut,
)
from app.services import browse

router = APIRouter(prefix="/api/tenants", tags=["browse"])


def database() -> Iterator[Session]:
    """A session, or a 503 when the database is not configured or cannot be reached."""
    try:
        yield from get_db()
    except (DatabaseNotConfiguredError, OperationalError) as err:
        raise DatabaseUnavailableError("Database unavailable") from err


Db = Annotated[Session, Depends(database)]
Kind = Annotated[str | None, Query(pattern="^(" + "|".join(ENTITY_KINDS) + ")$")]


@router.get("", response_model=list[TenantOut])
def list_tenants(db: Db):
    return [
        TenantOut(id=t.id, name=t.name, slug=t.omerlo_media_id) for t in browse.list_tenants(db)
    ]


@router.get("/{tenant_id}/runs", response_model=list[SyncRunOut])
def list_runs(tenant_id: uuid.UUID, db: Db):
    browse.get_tenant(db, tenant_id)
    return [
        SyncRunOut.model_validate(run, from_attributes=True)
        for run in browse.list_runs(db, tenant_id)
    ]


@router.get("/{tenant_id}/runs/{run_id}/changes", response_model=list[ChangeOut])
def run_changes(tenant_id: uuid.UUID, run_id: uuid.UUID, db: Db):
    browse.get_tenant(db, tenant_id)
    return [
        ChangeOut(
            change_type=change.change_type,
            kind=record.kind,
            source_id=record.source_id,
            external_id=record.external_id,
            label=browse.label(record),
            changed_fields=change.changed_fields,
        )
        for change, record in browse.run_changes(db, tenant_id, run_id)
    ]


@router.get("/{tenant_id}/records", response_model=list[RecordOut])
def search_records(
    tenant_id: uuid.UUID,
    db: Db,
    kind: Kind = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
):
    browse.get_tenant(db, tenant_id)
    return [
        RecordOut(
            source_id=r.source_id,
            external_id=r.external_id,
            kind=r.kind,
            label=browse.label(r),
            domain=r.domain,
            linkedin=r.linkedin,
            valid_from=r.valid_from,
        )
        for r in browse.search_records(db, tenant_id, kind=kind, query=q)
    ]


@router.get("/{tenant_id}/records/{source_id}/{external_id}", response_model=RecordHistoryOut)
def record_history(tenant_id: uuid.UUID, source_id: uuid.UUID, external_id: str, db: Db):
    browse.get_tenant(db, tenant_id)
    versions, changes = browse.record_history(db, tenant_id, source_id, external_id)
    started = browse.run_order(db, {c.sync_run_id for cs in changes.values() for c in cs})
    return RecordHistoryOut(
        source_id=source_id,
        external_id=external_id,
        kind=versions[-1].kind,
        versions=[
            VersionOut(
                id=v.id,
                label=browse.label(v),
                name_normalized=v.name_normalized,
                domain=v.domain,
                linkedin=v.linkedin,
                external_ids=v.external_ids,
                valid_from=v.valid_from,
                valid_to=v.valid_to,
                first_seen_run=v.first_seen_run,
                removed_run=v.removed_run,
                events=[
                    VersionEvent(
                        sync_run_id=c.sync_run_id,
                        change_type=c.change_type,
                        changed_fields=c.changed_fields,
                    )
                    for c in sorted(changes.get(v.id, []), key=lambda c: started[c.sync_run_id])
                ],
            )
            for v in versions
        ],
    )
