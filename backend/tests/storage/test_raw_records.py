"""archive_records and read_run with the database mocked; tests/integration covers the queries."""

import uuid
from datetime import UTC, datetime

import pytest

from app.ingestion.connector import RawRecord
from app.models import RawRecord as RawRecordRow
from app.models import SyncRun
from app.storage.archive import (
    ArchiveError,
    ArchiveIntegrityError,
    canonical_json,
    payload_hash,
)
from app.storage.local import LocalArchive
from app.storage.raw_records import archive_records, read_run

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
RUN = SyncRun(id=uuid.uuid4(), tenant_id=TENANT, source_id=uuid.uuid4())
PAYLOAD = {"id": "org-1", "name": "Acme", "updated_at": "2026-10-01T12:00:00Z"}


@pytest.fixture
def archive(tmp_path):
    return LocalArchive(tmp_path)


@pytest.fixture
def session(mocker):
    session = mocker.MagicMock()
    session.execute.return_value = []
    return session


def record(external_id="org-1", payload=PAYLOAD, kind="organization"):
    return RawRecord(kind, external_id, None, payload)


def test_archive_records_stores_each_payload_and_adds_a_row(session, archive):
    # Act
    rows = archive_records(session, archive, RUN, [record()])

    # Assert
    data = canonical_json(PAYLOAD)
    [row] = rows
    assert (row.tenant_id, row.sync_run_id) == (TENANT, RUN.id)
    assert (row.entity_kind, row.external_id) == ("organization", "org-1")
    assert row.payload_hash == payload_hash(data)
    assert archive.get(row.payload_uri, TENANT) == data
    session.add_all.assert_called_once_with(rows)
    session.flush.assert_called_once()


def test_archive_records_reuses_the_previous_copy_when_the_hash_is_unchanged(
    session, archive, mocker
):
    # Arrange
    digest = payload_hash(canonical_json(PAYLOAD))
    previous_uri = "file:///previous-run/copy.json"
    session.execute.return_value = [("organization", "org-1", previous_uri, digest)]
    put = mocker.spy(archive, "put")

    # Act
    [row] = archive_records(session, archive, RUN, [record()])

    # Assert
    assert row.payload_uri == previous_uri
    assert row.payload_hash == digest
    put.assert_not_called()


def test_archive_records_stores_a_changed_payload_again(session, archive):
    # Arrange
    session.execute.return_value = [("organization", "org-1", "file:///old.json", "0" * 64)]

    # Act
    [row] = archive_records(session, archive, RUN, [record()])

    # Assert
    assert row.payload_uri != "file:///old.json"
    assert archive.get(row.payload_uri, TENANT) == canonical_json(PAYLOAD)


def test_archive_records_stores_a_repeated_payload_once_within_a_run(session, archive, mocker):
    # Arrange
    put = mocker.spy(archive, "put")

    # Act
    first, second = archive_records(session, archive, RUN, [record(), record()])

    # Assert
    assert first.payload_uri == second.payload_uri
    put.assert_called_once()


def test_archive_records_rejects_kinds_raw_record_does_not_accept(session, archive):
    # Act / Assert
    with pytest.raises(ArchiveError, match="workspace"):
        archive_records(session, archive, RUN, [record(kind="workspace")])


def test_read_run_rebuilds_the_raw_records_from_the_archive(session, archive):
    # Arrange
    [row] = archive_records(session, archive, RUN, [record()])
    session.scalars.return_value = [row]

    # Act
    [rebuilt] = read_run(session, archive, TENANT, RUN.id)

    # Assert
    assert rebuilt == RawRecord(
        entity_kind="organization",
        external_id="org-1",
        updated_at=datetime(2026, 10, 1, 12, tzinfo=UTC),
        payload=PAYLOAD,
    )


def test_read_run_rejects_a_payload_that_no_longer_matches_its_hash(session, archive):
    # Arrange
    [row] = archive_records(session, archive, RUN, [record()])
    tampered = RawRecordRow(
        tenant_id=TENANT,
        sync_run_id=RUN.id,
        external_id="org-1",
        entity_kind="organization",
        payload_uri=row.payload_uri,
        payload_hash="0" * 64,
    )
    session.scalars.return_value = [tampered]

    # Act / Assert
    with pytest.raises(ArchiveIntegrityError):
        list(read_run(session, archive, TENANT, RUN.id))
