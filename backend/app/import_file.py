# AI contribution: 50% or more AI-generated
"""Import a CSV or JSON file of organizations or people as a sync run of a tenant's csv source.

uv run python -m app.import_file --tenant demo-capitale --kind organization organizations.csv
uv run python -m app.import_file --tenant demo-capitale --kind person people.json --full
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_session_factory
from app.core.logging import configure_logging
from app.core.tenancy import bound_to_tenant, system_access
from app.ingestion.files.columns import LAYOUTS
from app.ingestion.files.connector import FileConnector
from app.ingestion.files.reader import ImportFileError
from app.models import Source, SyncRun, Tenant
from app.services.sync_runs import FileReader, run_sync
from app.storage.settings import create_archive
from app.sync import SyncCommandError, find_source, find_tenant, summary

FILE_KINDS = ("csv",)


def file_source(session: Session, tenant: Tenant, source_id: str | None) -> Source:
    """The tenant's csv source, created on its first import."""
    if source_id is None:
        existing = select(Source.id).where(Source.tenant_id == tenant.id, Source.kind == "csv")
        if session.scalar(existing.limit(1)) is None:
            source = Source(tenant_id=tenant.id, kind="csv", config={})
            session.add(source)
            session.commit()
            return source
    return find_source(session, tenant, source_id, FILE_KINDS)


def import_file(
    session: Session,
    tenant_key: str,
    path: Path,
    kind: str,
    source_id: str | None,
    *,
    full: bool,
) -> SyncRun:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise SyncCommandError(f"Cannot read {path}: {error.strerror}") from None
    connector = FileConnector(data, path.name, kind)
    # Finding the tenant by its slug looks across tenants; everything after is scoped to it.
    with system_access(session):
        tenant = find_tenant(session, tenant_key)
    with bound_to_tenant(session, tenant.id):
        source = file_source(session, tenant, source_id)
        return run_sync(session, source, FileReader(connector), create_archive(), full=full)


def report(run: SyncRun) -> str:
    """The run's summary and the rejected rows kept on it."""
    lines = [summary(run)]
    failures = (run.counts or {}).get("failures", [])
    if failures:
        lines.append("Rejected rows:")
        lines += [f"  {failure['reason']}" for failure in failures]
        hidden = run.counts.get("failed", 0) - len(failures)
        if hidden > 0:
            lines.append(f"  ...and {hidden} more")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Import a CSV or JSON file into a tenant.")
    parser.add_argument("file", type=Path, help="the .csv or .json file to import")
    parser.add_argument("--tenant", required=True, help="tenant id or Omerlo media slug")
    parser.add_argument("--kind", required=True, choices=sorted(LAYOUTS), help="what the rows are")
    parser.add_argument("--source", help="csv source id; optional when the tenant has one")
    parser.add_argument(
        "--full",
        action="store_true",
        help="mark records of this kind missing from the file removed",
    )
    args = parser.parse_args(argv)
    configure_logging()

    with get_session_factory()() as session:
        try:
            run = import_file(
                session, args.tenant, args.file, args.kind, args.source, full=args.full
            )
        except (SyncCommandError, ImportFileError) as error:
            parser.exit(2, f"error: {error}\n")
        print(report(run))
        succeeded = run.status == "succeeded"
    if not succeeded:
        sys.exit(1)


if __name__ == "__main__":
    main()
