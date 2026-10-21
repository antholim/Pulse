"""Archive a sync run's raw records and read them back for reprocessing."""

import json
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import batched

from sqlalchemy import and_, select, tuple_
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.ingestion.connector import RawRecord
from app.models import RawRecord as RawRecordRow
from app.models import SyncRun
from app.models.records import RAW_ENTITY_KINDS
from app.storage.archive import (
    ArchiveError,
    ArchiveIntegrityError,
    PayloadArchive,
    archive_key,
    canonical_json,
    payload_hash,
)

LOOKUP_BATCH_SIZE = 500


@dataclass(frozen=True)
class Archived:
    uri: str
    digest: str


def archive_records(
    session: Session,
    archive: PayloadArchive,
    run: SyncRun,
    records: Iterable[RawRecord],
) -> list[RawRecordRow]:
    """Archive each payload and add a raw_record row for it to `session` (flushed, not committed).

    A payload whose hash equals the previous version of the same record from this
    source is not stored again: its row points at the archived copy.
    """
    rows: list[RawRecordRow] = []
    for chunk in batched(records, LOOKUP_BATCH_SIZE):
        latest = _latest_archived(session, run, chunk)
        for record in chunk:
            if record.entity_kind not in RAW_ENTITY_KINDS:
                raise ArchiveError(f"raw_record does not accept entity kind {record.entity_kind!r}")
            data = canonical_json(record.payload)
            digest = payload_hash(data)
            ident = (record.entity_kind, record.external_id)
            previous = latest.get(ident)
            if previous is None or previous.digest != digest:
                key = archive_key(run.tenant_id, run.id, record.entity_kind, digest)
                previous = Archived(archive.put(key, data), digest)
                latest[ident] = previous
            rows.append(
                RawRecordRow(
                    tenant_id=run.tenant_id,
                    sync_run_id=run.id,
                    external_id=record.external_id,
                    entity_kind=record.entity_kind,
                    payload_uri=previous.uri,
                    payload_hash=digest,
                    updated_at=record.updated_at,
                    parent_external_id=record.parent_external_id,
                )
            )
        session.add_all(rows[-len(chunk) :])
        session.flush()
    return rows


def _latest_archived(
    session: Session, run: SyncRun, records: Iterable[RawRecord]
) -> dict[tuple[str, str], Archived]:
    """The most recently archived payload of each record, from any run of the same source."""
    idents = {(r.entity_kind, r.external_id) for r in records}
    statement = (
        select(
            RawRecordRow.entity_kind,
            RawRecordRow.external_id,
            RawRecordRow.payload_uri,
            RawRecordRow.payload_hash,
        )
        .join(
            SyncRun,
            and_(
                SyncRun.tenant_id == RawRecordRow.tenant_id,
                SyncRun.id == RawRecordRow.sync_run_id,
            ),
        )
        .where(
            RawRecordRow.tenant_id == run.tenant_id,
            SyncRun.source_id == run.source_id,
            tuple_(RawRecordRow.entity_kind, RawRecordRow.external_id).in_(sorted(idents)),
        )
        .order_by(
            RawRecordRow.entity_kind,
            RawRecordRow.external_id,
            # Rows of the run being archived are the newest.
            (SyncRun.id == run.id).desc(),
            SyncRun.started_at.desc(),
        )
        .ext(distinct_on(RawRecordRow.entity_kind, RawRecordRow.external_id))
    )
    return {
        (kind, external_id): Archived(uri, digest)
        for kind, external_id, uri, digest in session.execute(statement)
    }


def read_run(
    session: Session, archive: PayloadArchive, tenant_id: uuid.UUID, sync_run_id: uuid.UUID
) -> Iterator[RawRecord]:
    """Yield the raw records a sync run archived, rebuilt from the archive, for reprocessing."""
    statement = (
        select(RawRecordRow)
        .where(RawRecordRow.tenant_id == tenant_id, RawRecordRow.sync_run_id == sync_run_id)
        .order_by(RawRecordRow.entity_kind, RawRecordRow.external_id, RawRecordRow.id)
    )
    for row in session.scalars(statement):
        data = archive.get(row.payload_uri, tenant_id)
        if payload_hash(data) != row.payload_hash:
            raise ArchiveIntegrityError(
                f"Archived payload of {row.entity_kind} {row.external_id} does not match its hash"
            )
        payload = json.loads(data)
        yield RawRecord(
            entity_kind=row.entity_kind,
            external_id=row.external_id,
            updated_at=row.updated_at,
            payload=payload,
            parent_external_id=row.parent_external_id,
        )
