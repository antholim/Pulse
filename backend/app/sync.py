"""Run one sync of a tenant's source and print the recorded sync run.

uv run python -m app.sync --tenant demo-capitale            # incremental
uv run python -m app.sync --tenant demo-capitale --full     # also marks removed records
"""

import argparse
import sys
import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_session_factory
from app.core.logging import configure_logging
from app.ingestion.omerlo.client import create_omerlo_client
from app.ingestion.omerlo.connector import OmerloConnector
from app.ingestion.omerlo.settings import OmerloSettings
from app.models import Source, SyncRun, Tenant
from app.seed import MOCK_OMERLO_BASE_URL
from app.services.sync_runs import COUNT_KEYS, run_sync
from app.storage.settings import create_archive


class SyncCommandError(Exception):
    """The command cannot start a sync, e.g. the tenant or source does not exist."""


def find_tenant(session: Session, key: str) -> Tenant:
    """A tenant by id or by Omerlo media slug."""
    try:
        condition = Tenant.id == uuid.UUID(key)
    except ValueError:
        condition = Tenant.omerlo_media_id == key
    tenant = session.scalar(select(Tenant).where(condition))
    if tenant is None:
        raise SyncCommandError(f"No tenant {key!r}")
    return tenant


def find_source(session: Session, tenant: Tenant, source_id: str | None) -> Source:
    """The tenant's source with that id, or its only source when no id is given."""
    statement = select(Source).where(Source.tenant_id == tenant.id)
    if source_id is not None:
        try:
            statement = statement.where(Source.id == uuid.UUID(source_id))
        except ValueError:
            raise SyncCommandError(f"Source id {source_id!r} is not a UUID") from None
    sources = session.scalars(statement).all()
    if not sources:
        raise SyncCommandError(f"Tenant {tenant.name!r} has no source {source_id or ''}".strip())
    if len(sources) > 1:
        ids = ", ".join(str(s.id) for s in sources)
        raise SyncCommandError(f"Tenant {tenant.name!r} has several sources, pick one: {ids}")
    return sources[0]


def omerlo_settings(source: Source, tenant: Tenant) -> OmerloSettings:
    """Connection settings: the source's base URL, the key from OMERLO_API_KEY.

    A mock source uses the mock server's key for the tenant, `mock-<slug>`.
    """
    config = source.config or {}
    if source.kind == "mock":
        if not tenant.omerlo_media_id:
            raise SyncCommandError("A mock source needs a tenant with an Omerlo media slug")
        return OmerloSettings(
            base_url=config.get("base_url") or MOCK_OMERLO_BASE_URL,
            api_key=f"mock-{tenant.omerlo_media_id}",
        )
    if source.kind == "omerlo":
        overrides = {"base_url": config["base_url"]} if config.get("base_url") else {}
        return OmerloSettings(**overrides)
    raise SyncCommandError(f"Sources of kind {source.kind!r} cannot be synced yet")


def summary(run: SyncRun) -> str:
    counts = ", ".join(f"{key} {run.counts.get(key, 0)}" for key in COUNT_KEYS)
    line = f"Sync run {run.id} ({run.mode}) {run.status}: {counts}"
    return f"{line}\n{run.error}" if run.error else line


def sync(session: Session, tenant_key: str, source_id: str | None, *, full: bool) -> SyncRun:
    tenant = find_tenant(session, tenant_key)
    source = find_source(session, tenant, source_id)
    settings = omerlo_settings(source, tenant)
    with create_omerlo_client(settings) as client:
        connector = OmerloConnector(client, workspace_ids=source.config.get("workspace_ids"))
        return run_sync(session, source, connector, create_archive(), full=full)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run one sync of a tenant's source.")
    parser.add_argument("--tenant", required=True, help="tenant id or Omerlo media slug")
    parser.add_argument("--source", help="source id; optional when the tenant has one source")
    parser.add_argument(
        "--full", action="store_true", help="fetch everything and mark missing records removed"
    )
    args = parser.parse_args(argv)
    configure_logging()

    with get_session_factory()() as session:
        try:
            run = sync(session, args.tenant, args.source, full=args.full)
        except SyncCommandError as error:
            parser.exit(2, f"error: {error}\n")
        print(summary(run))
        succeeded = run.status == "succeeded"
    if not succeeded:
        sys.exit(1)


if __name__ == "__main__":
    main()
