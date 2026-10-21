"""Run one sync of a source: fetch, archive, map and store versions, recorded as a sync_run."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.logging import logged_run
from app.ingestion.connector import RawRecord, parse_timestamp
from app.ingestion.omerlo.connector import OmerloConnector
from app.ingestion.omerlo.mapping.batch import map_records
from app.models import Source, SyncRun
from app.services.record_changes import record_changes
from app.services.source_records import close_unseen, upsert_records
from app.storage.archive import PayloadArchive
from app.storage.raw_records import archive_records

COUNT_KEYS = ("fetched", "new", "changed", "unchanged", "removed", "failed")
MAX_ERROR_LENGTH = 2000

# {workspace_id: {entity_kind: newest updated_at}}
WorkspaceWatermarks = dict[str, dict[str, datetime]]


# Writes the run's record_change rows in the run's transaction, returning counts per type.
ChangeDetector = Callable[[Session, SyncRun], dict[str, int]]


@dataclass
class Fetched:
    records: list[RawRecord] = field(default_factory=list)
    # Newest updated_at seen in the source-wide lists, and per workspace and kind.
    source_newest: datetime | None = None
    workspace_newest: WorkspaceWatermarks = field(default_factory=dict)


def utc_now() -> datetime:
    return datetime.now(UTC)


def run_sync(
    session: Session,
    source: Source,
    connector: OmerloConnector,
    archive: PayloadArchive,
    *,
    full: bool = False,
    detect_changes: ChangeDetector = record_changes,
    now: Callable[[], datetime] = utc_now,
) -> SyncRun:
    """Run one sync of `source` and return its sync_run, committed whatever the outcome.

    A failed run is recorded with its error; the versions and watermarks it would have
    written are rolled back, so the previous data stays as it was.
    """
    run = SyncRun(
        tenant_id=source.tenant_id,
        source_id=source.id,
        started_at=now(),
        status="running",
        mode="full" if full else "incremental",
        counts={},
    )
    session.add(run)
    session.commit()

    counts = dict.fromkeys(COUNT_KEYS, 0)
    try:
        with logged_run("sync", str(source.id), str(run.id)) as logged:
            try:
                fetched = fetch(connector, source, full=full)
                counts["fetched"] = len(fetched.records)
                archive_records(session, archive, run, fetched.records)
                # Kept even if storing fails, so the run can be reprocessed from the archive.
                session.commit()
                counts.update(store(session, run, source, fetched, detect_changes))
                finish(run, "succeeded", counts, now())
                session.commit()
            finally:
                logged.update(counts)
    except Exception as error:
        session.rollback()
        run.counts = {}
        # Counts of the rolled back writes would describe data that is not there.
        failed_counts = {**dict.fromkeys(COUNT_KEYS, 0), "fetched": counts["fetched"]}
        finish(run, "failed", failed_counts, now(), error=describe(error))
        session.commit()
    return run


def fetch(connector: OmerloConnector, source: Source, *, full: bool) -> Fetched:
    """Every record changed since the source's watermarks, or every record in full mode.

    Each workspace and kind is read from its own watermark, so a workspace added later
    or a kind read just before a change is not skipped.
    """
    stored = {} if full else read_watermarks(source.workspace_watermarks)
    workspaces = connector.workspaces()
    since = None if full else source.watermark_updated_at
    fetched = Fetched(records=list(connector.fetch_reference(workspaces, since)))
    fetched.source_newest = newest(fetched.records)
    for kind in connector.community_kinds:
        for workspace in workspaces:
            workspace_id = workspace["id"]
            since = stored.get(workspace_id, {}).get(kind)
            records = list(connector.fetch_community(kind, workspace_id, since))
            fetched.records += records
            latest = newest(r for r in records if r.entity_kind == kind)
            if latest is not None:
                fetched.workspace_newest.setdefault(workspace_id, {})[kind] = latest
    return fetched


def store(
    session: Session,
    run: SyncRun,
    source: Source,
    fetched: Fetched,
    detect_changes: ChangeDetector,
) -> dict[str, int]:
    """Map and store the fetched records as versions and advance the watermarks.

    Runs in the caller's transaction; the source row stays locked until it commits, so
    two syncs of one source never write at the same time.
    """
    session.refresh(source, with_for_update=True)
    mapped = map_records(fetched.records)
    upserted = upsert_records(session, run, mapped.records)
    removed: list[str] = []
    if run.mode == "full":
        removed = close_unseen(session, run, keep={f.external_id for f in mapped.failures})
    # Reads the versions this run opened and closed, so it comes after both.
    detect_changes(session, run)
    advance_watermarks(source, fetched)
    return {
        "new": len(upserted.added),
        "changed": len(upserted.changed),
        "unchanged": len(upserted.unchanged),
        "removed": len(removed),
        "failed": len(mapped.failures),
    }


def finish(
    run: SyncRun, status: str, counts: dict[str, int], at: datetime, error: str | None = None
) -> None:
    run.status = status
    # Keeps what change detection added to the counts.
    run.counts = {**(run.counts or {}), **counts}
    run.finished_at = max(at, run.started_at)
    run.error = error


def describe(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"[:MAX_ERROR_LENGTH]


def newest(records: Iterable[RawRecord]) -> datetime | None:
    return max((r.updated_at for r in records if r.updated_at is not None), default=None)


def read_watermarks(stored: dict) -> WorkspaceWatermarks:
    """Parse the source's stored watermarks, skipping any value that is not a timestamp."""
    parsed: WorkspaceWatermarks = {}
    for workspace_id, kinds in (stored or {}).items():
        if not isinstance(kinds, dict):
            continue
        for kind, value in kinds.items():
            moment = parse_timestamp(value)
            if moment is not None:
                parsed.setdefault(workspace_id, {})[kind] = moment
    return parsed


def advance_watermarks(source: Source, fetched: Fetched) -> None:
    """Move each watermark to the newest updated_at seen; a watermark never goes back."""
    if fetched.source_newest is not None:
        current = source.watermark_updated_at
        source.watermark_updated_at = max(filter(None, (current, fetched.source_newest)))
    merged = read_watermarks(source.workspace_watermarks)
    for workspace_id, kinds in fetched.workspace_newest.items():
        for kind, moment in kinds.items():
            previous = merged.setdefault(workspace_id, {}).get(kind)
            merged[workspace_id][kind] = max(filter(None, (previous, moment)))
    # A new dict, so the JSON column is seen as changed.
    source.workspace_watermarks = {
        workspace_id: {kind: moment.isoformat() for kind, moment in kinds.items()}
        for workspace_id, kinds in merged.items()
    }
