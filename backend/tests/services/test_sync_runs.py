# AI contribution: 50% or more AI-generated
"""Sync run orchestration with the database mocked; tests/integration runs it for real."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.ingestion.connector import RawRecord
from app.ingestion.omerlo.mapping.batch import MappingResult
from app.ingestion.omerlo.mapping.mappers import MappedRecord
from app.models import Source
from app.services import sync_runs
from app.services.source_records import UpsertResult
from app.services.sync_runs import (
    Fetched,
    OmerloReader,
    advance_watermarks,
    fetch,
    read_watermarks,
    run_sync,
)

T1 = datetime(2026, 10, 1, tzinfo=UTC)
T2 = T1 + timedelta(days=1)
T3 = T1 + timedelta(days=2)


def raw(kind, external_id, updated_at=None, parent=None):
    return RawRecord(kind, external_id, updated_at, {"id": external_id, "name": "Acme"}, parent)


class FakeConnector:
    """Serves fixed records per (kind, workspace) and remembers each watermark asked for."""

    community_kinds = ("organization", "person")

    def __init__(self, community=None, reference=(), error=None):
        self.community = community or {}
        self.reference = list(reference)
        self.error = error
        self.calls = []

    def workspaces(self):
        return [{"id": "ws-1"}, {"id": "ws-2"}]

    def fetch_reference(self, workspaces, watermark):
        self.calls.append(("reference", None, watermark))
        return iter(self.reference)

    def fetch_community(self, kind, workspace_id, watermark):
        self.calls.append((kind, workspace_id, watermark))
        if self.error:
            raise self.error
        return iter(self.community.get((kind, workspace_id), []))


def source(**watermarks):
    return Source(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        kind="mock",
        config={},
        watermark_updated_at=watermarks.pop("source", None),
        workspace_watermarks=watermarks.pop("workspaces", {}),
    )


def test_incremental_fetch_reads_each_workspace_and_kind_from_its_own_watermark():
    # Arrange
    stored = {"ws-1": {"organization": T1.isoformat()}, "ws-2": {"person": T2.isoformat()}}
    connector = FakeConnector()

    # Act
    fetch(connector, source(source=T3, workspaces=stored), full=False)

    # Assert
    assert connector.calls == [
        ("reference", None, T3),
        ("organization", "ws-1", T1),
        ("organization", "ws-2", None),
        ("person", "ws-1", None),
        ("person", "ws-2", T2),
    ]


def test_full_fetch_ignores_the_watermarks():
    # Arrange
    stored = {"ws-1": {"organization": T1.isoformat()}}
    connector = FakeConnector()

    # Act
    fetch(connector, source(source=T3, workspaces=stored), full=True)

    # Assert
    assert {watermark for *_, watermark in connector.calls} == {None}


def test_fetch_tracks_the_newest_update_per_workspace_and_kind():
    # Arrange
    connector = FakeConnector(
        community={
            ("organization", "ws-1"): [
                raw("organization", "o2", T2),
                raw("organization_metadata", "o2", parent="o2"),
                raw("organization", "o1", T1),
            ],
            ("person", "ws-2"): [raw("person", "p1", T3)],
        },
        reference=[raw("workspace", "ws-1", T1), raw("category", "c1", T2)],
    )

    # Act
    fetched = fetch(connector, source(), full=True)

    # Assert
    assert len(fetched.records) == 6
    assert fetched.source_newest == T2
    assert fetched.workspace_newest == {"ws-1": {"organization": T2}, "ws-2": {"person": T3}}


def test_read_watermarks_skips_values_that_are_not_timestamps():
    # Act
    parsed = read_watermarks(
        {"ws-1": {"organization": T1.isoformat(), "person": "soon"}, "ws-2": "broken"}
    )

    # Assert
    assert parsed == {"ws-1": {"organization": T1}}


def test_watermarks_advance_to_the_newest_update_and_never_go_back():
    # Arrange
    target = source(source=T2, workspaces={"ws-1": {"organization": T2.isoformat()}})
    fetched = Fetched(
        source_newest=T1,
        workspace_newest={"ws-1": {"organization": T1, "person": T3}, "ws-2": {"event": T1}},
    )

    # Act
    advance_watermarks(target, fetched)

    # Assert
    assert target.watermark_updated_at == T2
    assert target.workspace_watermarks == {
        "ws-1": {"organization": T2.isoformat(), "person": T3.isoformat()},
        "ws-2": {"event": T1.isoformat()},
    }


@pytest.fixture
def session(mocker):
    # A real info dict, where the session keeps its tenant scope.
    return mocker.MagicMock(info={})


@pytest.fixture
def stored(mocker):
    """The archive and the versioned upsert, mocked."""
    archive = mocker.patch.object(sync_runs, "archive_records")
    upsert = mocker.patch.object(
        sync_runs, "upsert_records", return_value=UpsertResult(["o1"], ["o2"], ["o3", "o4"])
    )
    close = mocker.patch.object(sync_runs, "close_unseen", return_value=["o5"])
    return archive, upsert, close


def clock():
    moments = iter([T1, T2, T3])
    return lambda: next(moments)


def org_reader():
    records = [raw("organization", "o1", T1)]
    return OmerloReader(FakeConnector(community={("organization", "ws-1"): records}))


def test_a_successful_run_records_its_counts_and_advances_the_watermarks(session, stored):
    # Arrange
    target = source()
    detected = []

    # Act
    run = run_sync(
        session,
        target,
        org_reader(),
        archive=None,
        full=True,
        now=clock(),
        detect_changes=lambda *args: detected.append(args),
    )

    # Assert
    assert (run.status, run.mode, run.started_at, run.finished_at) == ("succeeded", "full", T1, T2)
    assert run.counts == {
        "fetched": 1,
        "cleaning_flags": {},
        "new": 1,
        "changed": 1,
        "unchanged": 2,
        "removed": 1,
        "failed": 0,
    }
    assert target.workspace_watermarks == {"ws-1": {"organization": T1.isoformat()}}
    assert detected == [(session, run)]
    assert session.commit.call_count == 3


def test_an_incremental_run_never_marks_records_removed(session, stored):
    # Arrange
    _, _, close = stored

    # Act
    run = run_sync(session, source(), org_reader(), archive=None, now=clock())

    # Assert
    assert (run.mode, run.counts["removed"]) == ("incremental", 0)
    close.assert_not_called()


def test_a_fetch_error_fails_the_run_and_stores_nothing(session, stored):
    # Arrange
    archive, upsert, _ = stored
    target = source()
    connector = FakeConnector(error=httpx.ConnectError("connection refused"))

    # Act
    run = run_sync(session, target, OmerloReader(connector), archive=None, now=clock())

    # Assert
    assert run.status == "failed"
    assert run.error == "ConnectError: connection refused"
    assert run.counts == dict.fromkeys(sync_runs.COUNT_KEYS, 0)
    assert run.finished_at == T2
    archive.assert_not_called()
    upsert.assert_not_called()
    session.rollback.assert_called_once()
    assert target.workspace_watermarks == {}


def test_a_storage_error_keeps_only_the_fetched_count(session, stored):
    # Arrange
    _, upsert, _ = stored
    upsert.side_effect = RuntimeError("x" * 5000)

    # Act
    run = run_sync(session, source(), org_reader(), archive=None, now=clock())

    # Assert
    assert run.status == "failed"
    assert run.counts == {**dict.fromkeys(sync_runs.COUNT_KEYS, 0), "fetched": 1}
    assert len(run.error) == sync_runs.MAX_ERROR_LENGTH


def test_cleaning_counts_are_persisted_and_only_unique_records_reach_storage(session, stored):
    _, upsert, _ = stored
    record = raw("organization", "o1", T1)
    connector = FakeConnector(community={("organization", "ws-1"): [record, record]})

    run = run_sync(session, source(), OmerloReader(connector), archive=None, now=clock())

    assert run.status == "succeeded"
    assert run.counts["cleaning_flags"] == {"duplicate in current batch": 1}
    assert len(upsert.call_args.args[2]) == 1


class FakeReader:
    """A source that is not Omerlo: fixed records, mapped by a fixed result."""

    def __init__(self, records, mapped):
        self.records = records
        self.mapped = mapped

    def fetch(self, source, *, full):
        return Fetched(records=list(self.records))

    def map(self, records):
        return self.mapped


def test_any_reader_can_feed_a_sync_run(session, stored):
    # Arrange
    _, upsert, _ = stored
    mapped = MappedRecord(
        kind="organization", external_id="f1", workspace_id=None, name_normalized="acme"
    )
    reader = FakeReader([raw("organization", "f1")], MappingResult((mapped,), ()))

    # Act
    run = run_sync(session, source(), reader, archive=None, now=clock())

    # Assert
    assert run.status == "succeeded"
    assert upsert.call_args.args[2] == (mapped,)
    assert run.counts["fetched"] == 1


def test_required_cleaning_failure_does_not_abort_sync_or_remove_stored_record(session, stored):
    # Arrange
    _, upsert, close = stored
    connector = FakeConnector(
        community={
            ("organization", "ws-1"): [
                raw("organization", "NA", T1),
                raw("organization", "valid-org", T1),
            ],
        }
    )

    # Act
    run = run_sync(session, source(), OmerloReader(connector), archive=None, full=True, now=clock())

    # Assert
    assert run.status == "succeeded"
    assert run.counts["failed"] == 1
    assert run.counts["cleaning_flags"] == {"required field is missing": 1}
    assert [r.external_id for r in upsert.call_args.args[2]] == ["valid-org"]
    assert close.call_args.kwargs["keep"] == {"NA"}
    session.rollback.assert_not_called()
