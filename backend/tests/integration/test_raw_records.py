"""Archiving a run's payloads writes raw_record rows that reprocessing reads back."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.connector import RawRecord
from app.models import RawRecord as RawRecordRow
from app.models import Source, SyncRun, Tenant
from app.storage.archive import ArchiveAccessError
from app.storage.local import LocalArchive
from app.storage.raw_records import archive_records, read_run

pytestmark = pytest.mark.integration

ORG = RawRecord(
    "organization",
    "org-1",
    datetime(2026, 10, 1, 12, tzinfo=UTC),
    {"id": "org-1", "updated_at": "2026-10-01T12:00:00Z"},
)
SESSION = RawRecord("event_session", "s-1", None, {"id": "s-1"}, parent_external_id="e-1")
PERSON = RawRecord("person", "p-1", None, {"id": "p-1", "name": "Ada"})


def add_tenant(session: Session, name: str) -> tuple[Tenant, Source]:
    tenant = Tenant(name=name)
    session.add(tenant)
    session.flush()
    source = Source(tenant_id=tenant.id, kind="mock")
    session.add(source)
    session.flush()
    return tenant, source


def add_run(session: Session, source: Source, day: int) -> SyncRun:
    run = SyncRun(
        tenant_id=source.tenant_id,
        source_id=source.id,
        started_at=datetime(2026, 10, day, tzinfo=UTC),
    )
    session.add(run)
    session.flush()
    return run


@pytest.fixture
def archive(tmp_path):
    return LocalArchive(tmp_path)


def files(archive: LocalArchive) -> list[str]:
    return sorted(p.relative_to(archive.root).as_posix() for p in archive.root.rglob("*.json"))


def test_archived_payloads_are_recorded_and_read_back(session, archive):
    # Arrange
    tenant, source = add_tenant(session, "Tenant A")
    run = add_run(session, source, 1)

    # Act
    archive_records(session, archive, run, [ORG, PERSON, SESSION])
    rebuilt = list(read_run(session, archive, tenant.id, run.id))

    # Assert
    rows = session.scalars(select(RawRecordRow).where(RawRecordRow.sync_run_id == run.id)).all()
    assert len(rows) == 3
    assert all(row.payload_uri.startswith(archive.root.as_uri()) for row in rows)
    assert rebuilt == [SESSION, ORG, PERSON]
    assert all(f.startswith(f"tenants/{tenant.id}/runs/{run.id}/") for f in files(archive))


def test_an_unchanged_payload_is_not_stored_again_by_the_next_run(session, archive):
    # Arrange
    tenant, source = add_tenant(session, "Tenant A")
    first_run = add_run(session, source, 1)
    second_run = add_run(session, source, 2)
    changed = RawRecord("person", "p-1", None, {"id": "p-1", "name": "Ada Lovelace"})
    [first_org, _] = archive_records(session, archive, first_run, [ORG, PERSON])

    # Act
    second_org, second_person = archive_records(session, archive, second_run, [ORG, changed])

    # Assert
    assert second_org.payload_uri == first_org.payload_uri
    assert second_person.payload_uri.endswith(".json")
    assert f"/runs/{second_run.id}/person/" in second_person.payload_uri
    assert len(files(archive)) == 3
    rebuilt = list(read_run(session, archive, tenant.id, second_run.id))
    assert [r.payload for r in rebuilt] == [ORG.payload, changed.payload]


def test_the_same_payload_from_another_source_is_stored_separately(session, archive):
    # Arrange
    tenant, source = add_tenant(session, "Tenant A")
    other_source = Source(tenant_id=tenant.id, kind="csv")
    session.add(other_source)
    session.flush()
    archive_records(session, archive, add_run(session, source, 1), [ORG])

    # Act
    [row] = archive_records(session, archive, add_run(session, other_source, 2), [ORG])

    # Assert
    assert f"/runs/{row.sync_run_id}/" in row.payload_uri
    assert len(files(archive)) == 2


def test_another_tenant_cannot_read_a_runs_payloads(session, archive):
    # Arrange
    _, source_a = add_tenant(session, "Tenant A")
    tenant_b, source_b = add_tenant(session, "Tenant B")
    run_a = add_run(session, source_a, 1)
    [row] = archive_records(session, archive, run_a, [ORG])
    run_b = add_run(session, source_b, 1)
    session.add(
        RawRecordRow(
            tenant_id=tenant_b.id,
            sync_run_id=run_b.id,
            external_id="org-1",
            entity_kind="organization",
            payload_uri=row.payload_uri,
            payload_hash=row.payload_hash,
        )
    )
    session.flush()

    # Act
    other_tenants_view = list(read_run(session, archive, tenant_b.id, run_a.id))

    # Assert: tenant B sees no rows of tenant A's run, and a copied URI is refused.
    assert other_tenants_view == []
    with pytest.raises(ArchiveAccessError):
        list(read_run(session, archive, tenant_b.id, run_b.id))
