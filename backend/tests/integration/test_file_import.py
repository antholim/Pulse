# AI contribution: 50% or more AI-generated
"""File imports end to end: archive, versioned records and changes on a real database."""

import time
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import bound_to_tenant
from app.ingestion.files.connector import FileConnector
from app.models import RawRecord as RawRecordRow
from app.models import RecordChange, Source, SourceRecord, SyncRun, Tenant
from app.services.sync_runs import FileReader, run_sync
from app.storage.local import LocalArchive
from tests.integration.test_sync_runs import Clock

pytestmark = pytest.mark.integration

SAMPLES = Path(__file__).resolve().parents[2] / "synthetic" / "samples"
HEADER = "id,name,website,email"


class Importer:
    """Imports files into one csv source, each run a minute after the previous one."""

    def __init__(self, session: Session, source: Source, archive: LocalArchive):
        self.session, self.source, self.archive, self.clock = session, source, archive, Clock()

    def run(
        self, data: bytes, name: str = "organizations.csv", kind: str = "organization", **options
    ) -> SyncRun:
        reader = FileReader(FileConnector(data, name, kind))
        return run_sync(self.session, self.source, reader, self.archive, now=self.clock, **options)


def add_source(session: Session, name: str) -> Source:
    tenant = Tenant(name=name)
    session.add(tenant)
    session.flush()
    source = Source(tenant_id=tenant.id, kind="csv", config={})
    session.add(source)
    session.commit()
    return source


@pytest.fixture
def importer(session, tmp_path):
    return Importer(session, add_source(session, "Tenant A"), LocalArchive(tmp_path / "archive"))


def org_file(*rows: str) -> bytes:
    return ("\n".join((HEADER, *rows)) + "\n").encode()


def current(session: Session, kind: str | None = None) -> dict[str, SourceRecord]:
    statement = select(SourceRecord).where(SourceRecord.valid_to.is_(None))
    if kind is not None:
        statement = statement.where(SourceRecord.kind == kind)
    return {record.external_id: record for record in session.scalars(statement)}


def changes(session: Session, run: SyncRun) -> dict[str, tuple[str, dict]]:
    statement = (
        select(SourceRecord.external_id, RecordChange)
        .join(SourceRecord, SourceRecord.id == RecordChange.source_record_id)
        .where(RecordChange.sync_run_id == run.id)
    )
    return {
        external_id: (change.change_type, change.changed_fields)
        for external_id, change in session.execute(statement)
    }


def test_the_sample_files_import_with_their_invalid_rows_rejected(session, importer):
    # Act
    organizations = importer.run((SAMPLES / "organizations.csv").read_bytes())
    people = importer.run((SAMPLES / "people.json").read_bytes(), "people.json", "person")

    # Assert
    assert (organizations.status, people.status) == ("succeeded", "succeeded")
    assert organizations.counts["failures"] == [
        {"id": "organization:106", "reason": "row 7: email is not an email address"}
    ]
    assert people.counts["failures"] == [
        {"id": "person:p-204", "reason": "row 4: first_name or last_name is needed"}
    ]
    records = current(session)
    assert len(records) == 8
    assert {record.tenant_id for record in records.values()} == {importer.source.tenant_id}
    boreal = records["organization:101"]
    assert (boreal.name_normalized, boreal.domain, boreal.city) == (
        "atelier boreal",
        "atelierboreal.qc.ca",
        "quebec",
    )
    assert boreal.linkedin == "company/atelier-boreal"


def test_the_file_and_each_valid_row_are_archived_with_the_run(session, importer):
    # Act
    run = importer.run(org_file("1,Acme,acme.ca,", "2,Beta,,bad"))

    # Assert
    rows = session.scalars(select(RawRecordRow).where(RawRecordRow.sync_run_id == run.id)).all()
    assert sorted((row.entity_kind, row.external_id) for row in rows) == [
        ("import_file", "organizations.csv"),
        ("organization", "organization:1"),
    ]


def test_reimporting_an_edited_file_records_what_changed(session, importer):
    # Arrange
    importer.run(org_file("1,Acme,acme.ca,", "2,Beta,beta.ca,", "3,Gamma,,"))

    # Act
    run = importer.run(
        org_file("1,Acme,acme.ca,", "2,Beta Nord,beta.ca,", "3,Gamma,,", "4,Delta,,")
    )

    # Assert
    assert (run.counts["new"], run.counts["changed"], run.counts["unchanged"]) == (1, 1, 2)
    found = changes(session, run)
    assert set(found) == {"organization:2", "organization:4"}
    assert found["organization:4"] == ("added", {})
    change_type, fields = found["organization:2"]
    assert change_type == "modified"
    assert fields["name_normalized"] == {"before": "beta", "after": "beta nord"}
    assert fields["attributes.name"] == {"before": "Beta", "after": "Beta Nord"}


def test_a_full_import_removes_missing_rows_of_its_own_kind_only(session, importer):
    # Arrange
    importer.run(b"id,first_name,last_name\np1,Jean,Roy\n", "people.csv", "person")
    importer.run(org_file("1,Acme,,", "2,Beta,,"))

    # Act
    run = importer.run(org_file("1,Acme,,"), full=True)

    # Assert
    assert run.counts["removed"] == 1
    assert changes(session, run) == {"organization:2": ("removed", {})}
    assert set(current(session)) == {"organization:1", "person:p1"}


def test_an_incremental_import_never_removes_missing_rows(session, importer):
    # Arrange
    importer.run(org_file("1,Acme,,", "2,Beta,,"))

    # Act
    run = importer.run(org_file("1,Acme,,"))

    # Assert
    assert run.counts["removed"] == 0
    assert set(current(session)) == {"organization:1", "organization:2"}


def test_a_full_import_keeps_a_record_whose_row_was_rejected(session, importer):
    # Arrange
    importer.run(org_file("1,Acme,,", "2,Beta,,"))

    # Act
    run = importer.run(org_file("1,Acme,,", "2,Beta,,not-an-email"), full=True)

    # Assert
    assert (run.counts["removed"], run.counts["failed"]) == (0, 1)
    assert "organization:2" in current(session)


def test_another_tenant_sees_none_of_the_imported_records(session, importer):
    # Arrange
    other = add_source(session, "Tenant B")
    importer.run(org_file("1,Acme,,"))

    # Act
    with bound_to_tenant(session, other.tenant_id):
        records = session.scalars(select(SourceRecord)).all()
        raw_records = session.scalars(select(RawRecordRow)).all()

    # Assert
    assert (records, raw_records) == ([], [])


def test_five_thousand_rows_import_in_seconds(session, importer):
    # Arrange
    rows = (f"{n},Organisation {n},org{n}.ca,info@org{n}.ca" for n in range(5000))

    # Act
    started = time.monotonic()
    run = importer.run(org_file(*rows))
    elapsed = time.monotonic() - started

    # Assert
    assert (run.status, run.counts["new"]) == ("succeeded", 5000)
    assert elapsed < 30
