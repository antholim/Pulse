"""Record what a sync run added, modified and removed, and diff any two runs on demand."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import batched

from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.models import RecordChange, SourceRecord, SyncRun
from app.models.changes import CHANGE_TYPES
from app.processing.record_diff import FieldChanges, diff_snapshots, field_changes, snapshot
from app.services.source_records import BATCH_SIZE, as_of

# Key of sync_run.counts holding the number of changes per change type.
COUNTS_KEY = "changes"


@dataclass(frozen=True)
class Change:
    """One added, modified or removed record.

    `version_id` is the new version for added and modified records, and the last version
    for removed ones. `changed_fields` is empty unless the record was modified.
    """

    change_type: str
    kind: str
    external_id: str
    version_id: uuid.UUID
    changed_fields: FieldChanges


def record_changes(session: Session, run: SyncRun) -> dict[str, int]:
    """Write the record_change rows of `run` and its counts, in the caller's transaction.

    Call it after the run's upsert (and, for a full sync, after closing unseen records).
    Calling it again for the same run replaces its rows. Returns the counts per change type.
    """
    changes = run_changes(session, run)
    session.execute(
        delete(RecordChange).where(
            RecordChange.tenant_id == run.tenant_id, RecordChange.sync_run_id == run.id
        )
    )
    if changes:
        session.execute(
            insert(RecordChange),
            [
                {
                    "tenant_id": run.tenant_id,
                    "sync_run_id": run.id,
                    "source_record_id": change.version_id,
                    "change_type": change.change_type,
                    "changed_fields": change.changed_fields,
                }
                for change in changes
            ],
        )
    counts = count(changes)
    # A new dict, so the JSON column is seen as changed; other keys are kept.
    run.counts = {**(run.counts or {}), COUNTS_KEY: counts}
    session.flush()
    return counts


def run_changes(session: Session, run: SyncRun) -> list[Change]:
    """What `run` changed, read from the versions it opened and closed."""
    opened = list(
        session.scalars(
            select(SourceRecord).where(
                SourceRecord.tenant_id == run.tenant_id,
                SourceRecord.source_id == run.source_id,
                SourceRecord.first_seen_run == run.id,
            )
        )
    )
    removed = session.scalars(
        select(SourceRecord).where(
            SourceRecord.tenant_id == run.tenant_id,
            SourceRecord.source_id == run.source_id,
            SourceRecord.removed_run == run.id,
        )
    )
    previous = previous_versions(session, run, [version.external_id for version in opened])
    changes = [
        Change("removed", version.kind, version.external_id, version.id, {}) for version in removed
    ]
    for version in opened:
        before = previous.get(version.external_id)
        # The run closed the previous version at its start, unless it was removed earlier,
        # in which case the record came back and counts as added.
        if before is None or before.valid_to != run.started_at or before.removed_run:
            changes.append(Change("added", version.kind, version.external_id, version.id, {}))
            continue
        fields = field_changes(snapshot(before), snapshot(version))
        if fields:
            changes.append(
                Change("modified", version.kind, version.external_id, version.id, fields)
            )
    return sorted(changes, key=order)


def previous_versions(
    session: Session, run: SyncRun, external_ids: list[str]
) -> dict[str, SourceRecord]:
    """The latest version of each record that started before `run`."""
    found: dict[str, SourceRecord] = {}
    for batch in batched(external_ids, BATCH_SIZE):
        statement = (
            select(SourceRecord)
            .where(
                SourceRecord.tenant_id == run.tenant_id,
                SourceRecord.source_id == run.source_id,
                SourceRecord.external_id.in_(batch),
                SourceRecord.valid_from < run.started_at,
            )
            .ext(distinct_on(SourceRecord.external_id))
            .order_by(SourceRecord.external_id, SourceRecord.valid_from.desc())
            # The upsert closes versions with UPDATE statements; read their new valid_to.
            .execution_options(populate_existing=True)
        )
        found.update((version.external_id, version) for version in session.scalars(statement))
    return found


def diff_runs(session: Session, run_a: SyncRun, run_b: SyncRun) -> list[Change]:
    """The changes from the state of the source at `run_a` to its state at `run_b`.

    Both runs must belong to the same source. Nothing is written.
    """
    if (run_a.tenant_id, run_a.source_id) != (run_b.tenant_id, run_b.source_id):
        raise ValueError("both sync runs must belong to the same source")
    ids_a, ids_b = version_ids(session, run_a), version_ids(session, run_b)
    # Records whose version is the same at both runs did not change; skip loading them.
    differing = set(ids_a.values()) ^ set(ids_b.values())
    versions = {version.id: version for version in load(session, differing)}
    before = {key: versions[v] for key, v in ids_a.items() if v in versions}
    after = {key: versions[v] for key, v in ids_b.items() if v in versions}
    diff = diff_snapshots(
        {key: snapshot(version) for key, version in before.items()},
        {key: snapshot(version) for key, version in after.items()},
    )
    changes = [Change("added", after[k].kind, k, after[k].id, {}) for k in diff.added]
    changes += [Change("removed", before[k].kind, k, before[k].id, {}) for k in diff.removed]
    changes += [
        Change("modified", after[k].kind, k, after[k].id, fields)
        for k, fields in diff.modified.items()
    ]
    return sorted(changes, key=order)


def version_ids(session: Session, run: SyncRun) -> dict[str, uuid.UUID]:
    """External id to the id of its version valid at `run`."""
    statement = as_of(run).with_only_columns(SourceRecord.external_id, SourceRecord.id)
    return dict(session.execute(statement).tuples())


def load(session: Session, ids: Iterable[uuid.UUID]) -> list[SourceRecord]:
    versions: list[SourceRecord] = []
    for batch in batched(ids, BATCH_SIZE):
        versions += session.scalars(select(SourceRecord).where(SourceRecord.id.in_(batch)))
    return versions


def count(changes: Iterable[Change]) -> dict[str, int]:
    counts = dict.fromkeys(CHANGE_TYPES, 0)
    for change in changes:
        counts[change.change_type] += 1
    return counts


def order(change: Change) -> tuple[str, str, str]:
    return (change.kind, change.external_id, change.change_type)
