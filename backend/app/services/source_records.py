"""Store mapped records as source_record versions, keeping every earlier version."""

import uuid
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from itertools import batched

from sqlalchemy import Select, bindparam, or_, select, text, update
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Session

from app.ingestion.omerlo.mapping.mappers import MappedRecord
from app.models import SourceRecord, SyncRun
from app.processing.content_hash import content_hash

BATCH_SIZE = 1000

_ID_PAIRS = "unnest(CAST(:old_ids AS uuid[]), CAST(:new_ids AS uuid[])) AS m(old_id, new_id)"
_ID_ARRAYS = (bindparam("old_ids", type_=ARRAY(UUID)), bindparam("new_ids", type_=ARRAY(UUID)))

COPY_ORG_LINKS = text(
    f"""
    INSERT INTO org_link (source_record_id, organization_id, tenant_id, method, confidence,
                          decided_by, decided_at)
    SELECT m.new_id, l.organization_id, l.tenant_id, l.method, l.confidence, l.decided_by,
           l.decided_at
    FROM org_link l
    JOIN {_ID_PAIRS} ON l.source_record_id = m.old_id
    WHERE l.tenant_id = :tenant_id
    """
).bindparams(*_ID_ARRAYS)

# Moves both sides of each candidate to their new versions, keeping the pair ordered. Only
# pairs of two current versions are copied: a pair with an older version is history.
COPY_MATCH_CANDIDATES = text(
    f"""
    WITH m AS (SELECT * FROM {_ID_PAIRS}),
    touched AS (
        SELECT c.* FROM match_candidate c JOIN m ON c.left_record_id = m.old_id
        WHERE c.tenant_id = :tenant_id
        UNION
        SELECT c.* FROM match_candidate c JOIN m ON c.right_record_id = m.old_id
        WHERE c.tenant_id = :tenant_id
    ),
    moved AS (
        SELECT t.tenant_id, t.score, t.matched_fields, t.status,
               COALESCE(ml.new_id, t.left_record_id) AS a,
               COALESCE(mr.new_id, t.right_record_id) AS b
        FROM touched t
        LEFT JOIN m ml ON ml.old_id = t.left_record_id
        LEFT JOIN m mr ON mr.old_id = t.right_record_id
    )
    INSERT INTO match_candidate (tenant_id, left_record_id, right_record_id, score,
                                 matched_fields, status)
    SELECT mv.tenant_id, LEAST(mv.a, mv.b), GREATEST(mv.a, mv.b), mv.score,
           mv.matched_fields, mv.status
    FROM moved mv
    JOIN source_record sa ON sa.tenant_id = mv.tenant_id AND sa.id = mv.a
    JOIN source_record sb ON sb.tenant_id = mv.tenant_id AND sb.id = mv.b
    WHERE sa.valid_to IS NULL AND sb.valid_to IS NULL
    ON CONFLICT (tenant_id, left_record_id, right_record_id) DO NOTHING
    """
).bindparams(*_ID_ARRAYS)


@dataclass
class UpsertResult:
    """External ids by outcome; a record that reappears after removal counts as added."""

    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Plan:
    """What one batch writes, decided from the latest version of each record."""

    inserts: list[dict]
    to_close: list[uuid.UUID]
    to_touch: list[uuid.UUID]
    # (previous version, new version) whose links and candidates move to the new one.
    carried: list[tuple[uuid.UUID, uuid.UUID]]
    result: UpsertResult


@dataclass(frozen=True)
class Latest:
    """The newest version of a record, current or closed."""

    id: uuid.UUID
    content_hash: str
    current: bool


def upsert_records(
    session: Session,
    run: SyncRun,
    records: Iterable[MappedRecord],
    *,
    batch_size: int = BATCH_SIZE,
) -> UpsertResult:
    """Insert, version or touch each record in `run`, in the caller's transaction.

    A new version is valid from the run's start. When an external id appears more than
    once, the last occurrence wins.
    """
    unique = {record.external_id: record for record in records}
    result = UpsertResult()
    for batch in batched(unique.values(), batch_size):
        latest = latest_versions(session, run, [record.external_id for record in batch])
        plan = plan_batch(run, batch, latest)
        apply_plan(session, run, plan)
        result.added += plan.result.added
        result.changed += plan.result.changed
        result.unchanged += plan.result.unchanged
    return result


def plan_batch(run: SyncRun, batch: Iterable[MappedRecord], latest: dict[str, Latest]) -> Plan:
    """Sort a batch into new, changed and unchanged records; touches no database."""
    plan = Plan([], [], [], [], UpsertResult())
    for record in batch:
        digest = content_hash(record)
        previous = latest.get(record.external_id)
        if previous and previous.current and previous.content_hash == digest:
            plan.to_touch.append(previous.id)
            plan.result.unchanged.append(record.external_id)
            continue
        new_id = uuid.uuid4()
        plan.inserts.append(version_row(run, record, new_id, digest))
        if previous is None:
            plan.result.added.append(record.external_id)
            continue
        plan.carried.append((previous.id, new_id))
        if previous.current:
            plan.to_close.append(previous.id)
            plan.result.changed.append(record.external_id)
        else:
            plan.result.added.append(record.external_id)
    return plan


def apply_plan(session: Session, run: SyncRun, plan: Plan) -> None:
    if plan.to_touch:
        session.execute(
            update(SourceRecord)
            .where(SourceRecord.id.in_(plan.to_touch))
            .values(last_seen_run=run.id),
            execution_options={"synchronize_session": False},
        )
    # Close before inserting: the new version would otherwise be a second current one.
    if plan.to_close:
        session.execute(
            update(SourceRecord)
            .where(SourceRecord.id.in_(plan.to_close))
            .values(valid_to=run.started_at),
            execution_options={"synchronize_session": False},
        )
    if plan.inserts:
        session.execute(SourceRecord.__table__.insert(), plan.inserts)
    if plan.carried:
        old_ids, new_ids = (list(ids) for ids in zip(*plan.carried, strict=True))
        params = {"tenant_id": run.tenant_id, "old_ids": old_ids, "new_ids": new_ids}
        session.execute(COPY_ORG_LINKS, params)
        session.execute(COPY_MATCH_CANDIDATES, params)


def close_unseen(session: Session, run: SyncRun, *, keep: Collection[str] = ()) -> list[str]:
    """After a full sync, close and mark removed every current version `run` did not see.

    `keep` holds external ids that were fetched but could not be mapped, so they are not
    taken for removed. Returns the external ids closed.
    """
    statement = (
        update(SourceRecord)
        .where(
            SourceRecord.tenant_id == run.tenant_id,
            SourceRecord.source_id == run.source_id,
            SourceRecord.valid_to.is_(None),
            SourceRecord.last_seen_run != run.id,
        )
        .values(valid_to=run.started_at, removed_run=run.id)
        .returning(SourceRecord.external_id)
    )
    if keep:
        statement = statement.where(SourceRecord.external_id.not_in(list(keep)))
    rows = session.execute(statement, execution_options={"synchronize_session": False})
    return sorted(rows.scalars())


def latest_versions(session: Session, run: SyncRun, external_ids: list[str]) -> dict[str, Latest]:
    statement = (
        select(
            SourceRecord.external_id,
            SourceRecord.id,
            SourceRecord.content_hash,
            SourceRecord.valid_to,
        )
        .where(
            SourceRecord.tenant_id == run.tenant_id,
            SourceRecord.source_id == run.source_id,
            SourceRecord.external_id.in_(external_ids),
        )
        .distinct(SourceRecord.external_id)
        .order_by(
            SourceRecord.external_id,
            SourceRecord.valid_from.desc(),
            SourceRecord.valid_to.desc().nulls_first(),
        )
    )
    return {
        external_id: Latest(version_id, digest, valid_to is None)
        for external_id, version_id, digest, valid_to in session.execute(statement)
    }


def as_of(run: SyncRun) -> Select[tuple[SourceRecord]]:
    """The versions of the run's source that were valid at `run`, one per record."""
    return select(SourceRecord).where(
        SourceRecord.tenant_id == run.tenant_id,
        SourceRecord.source_id == run.source_id,
        SourceRecord.valid_from <= run.started_at,
        or_(SourceRecord.valid_to.is_(None), SourceRecord.valid_to > run.started_at),
    )


def version_as_of(session: Session, run: SyncRun, external_id: str) -> SourceRecord | None:
    """The version of one record valid at `run`, or None when it did not exist then."""
    statement = as_of(run).where(SourceRecord.external_id == external_id)
    # The upsert writes with UPDATE statements, so refresh any version already loaded.
    statement = statement.execution_options(populate_existing=True)
    return session.scalars(statement).one_or_none()


def version_row(run: SyncRun, record: MappedRecord, version_id: uuid.UUID, digest: str) -> dict:
    return {
        "id": version_id,
        "tenant_id": run.tenant_id,
        "source_id": run.source_id,
        "external_id": record.external_id,
        "kind": record.kind,
        "name_normalized": record.name_normalized,
        "domain": record.domain,
        "linkedin": record.linkedin,
        "external_ids": record.external_ids,
        "attributes": record.attributes,
        "workspace_id": record.workspace_id,
        "valid_from": run.started_at,
        "first_seen_run": run.id,
        "last_seen_run": run.id,
        "content_hash": digest,
    }
