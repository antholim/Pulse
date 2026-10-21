"""Sync runs against the mock Omerlo server and a real database."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import sync as sync_command
from app.ingestion.connector import parse_timestamp
from app.ingestion.omerlo.connector import OmerloConnector
from app.models import RawRecord as RawRecordRow
from app.models import Source, SourceRecord, SyncRun, Tenant
from app.seed import seed
from app.services.sync_runs import run_sync
from app.storage.local import LocalArchive
from synthetic.fixture_loader import load_fixtures
from synthetic.mock_omerlo import api_key_for, create_app
from synthetic.mutate import DEMO, apply_set
from synthetic.omerlo_fixtures import OmerloFixtureGenerator, write_fixtures
from tests.synthetic.conftest import SMALL

pytestmark = pytest.mark.integration

SEED = 5
SLUG = "demo-capitale"
# Fixture kind -> entity kind, for the records that become source records.
ENTITY_FILES = {
    "organizations": "organization",
    "people": "person",
    "projects": "project",
    "events": "event",
}


class Clock:
    """Each call is one minute after the previous one, so runs never share a start."""

    def __init__(self):
        self.moment = datetime(2026, 11, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.moment += timedelta(minutes=1)
        return self.moment


@pytest.fixture
def fixtures(tmp_path):
    out = tmp_path / "fixtures"
    write_fixtures(OmerloFixtureGenerator(SEED, SMALL).generate(), out, SEED)
    return out


@pytest.fixture
def mock_app(fixtures):
    return create_app(load_fixtures(fixtures), fixtures)


def mock_client(app, slug: str = SLUG) -> TestClient:
    return TestClient(app, base_url="http://mock/api", headers={"x-api-key": api_key_for(slug)})


@pytest.fixture
def client(mock_app):
    with mock_client(mock_app) as c:
        yield c


@pytest.fixture
def source(session):
    tenant = Tenant(name="Média démo Capitale", omerlo_media_id=SLUG)
    session.add(tenant)
    session.flush()
    source = Source(tenant_id=tenant.id, kind="mock")
    session.add(source)
    session.commit()
    return source


@pytest.fixture
def archive(tmp_path):
    return LocalArchive(tmp_path / "archive")


@pytest.fixture
def sync(session, source, client, archive):
    clock = Clock()

    def run(full: bool = False, **options) -> SyncRun:
        connector = OmerloConnector(options.pop("client", client))
        return run_sync(session, source, connector, archive, full=full, now=clock, **options)

    return run


def tenant_fixtures(fixtures):
    return next(t for t in load_fixtures(fixtures) if t.tenant.slug == SLUG)


def version_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(SourceRecord))


def current_ids(session: Session) -> set[str]:
    statement = select(SourceRecord.external_id).where(SourceRecord.valid_to.is_(None))
    return set(session.scalars(statement))


def ids_of(entries) -> set[str]:
    """Ids of the diff entries that are source records (not event sessions)."""
    return {entry["id"] for entry in entries if entry["kind"] in ENTITY_FILES}


def test_first_full_sync_stores_every_record_and_sets_the_watermarks(
    session, source, sync, fixtures
):
    # Arrange
    data = tenant_fixtures(fixtures)
    expected_ids = {r["id"] for kind in ENTITY_FILES for r in data.resources[kind]}

    # Act
    run = sync(full=True)

    # Assert
    assert (run.status, run.mode, run.error) == ("succeeded", "full", None)
    assert run.finished_at > run.started_at
    assert run.counts["new"] == len(expected_ids)
    assert {k: run.counts[k] for k in ("changed", "unchanged", "removed", "failed")} == {
        "changed": 0,
        "unchanged": 0,
        "removed": 0,
        "failed": 0,
    }
    assert current_ids(session) == expected_ids
    raw_rows = session.scalar(select(func.count()).where(RawRecordRow.sync_run_id == run.id))
    assert raw_rows == run.counts["fetched"]
    session.refresh(source)
    for workspace in data.resources["workspaces"]:
        for kind, entity_kind in ENTITY_FILES.items():
            in_workspace = [
                parse_timestamp(r["updated_at"])
                for r in data.resources[kind]
                if r["profile"]["workspace_id"] == workspace["id"]
            ]
            stored = source.workspace_watermarks[workspace["id"]][entity_kind]
            assert parse_timestamp(stored) == max(in_workspace)


def test_incremental_sync_after_the_demo_mutation_stores_what_changed(
    session, source, sync, fixtures
):
    # Arrange
    first = sync(full=True)
    session.refresh(source)
    before = dict(source.workspace_watermarks)
    diff = apply_set(fixtures, DEMO)["tenants"][SLUG]

    # Act
    run = sync()

    # Assert
    assert (run.status, run.mode) == ("succeeded", "incremental")
    assert run.counts["fetched"] < first.counts["fetched"]
    assert run.counts["new"] == len(ids_of(diff["added"]))
    assert run.counts["changed"] == len(ids_of(diff["modified"]))
    assert run.counts["removed"] == 0
    new_versions = select(SourceRecord.external_id).where(SourceRecord.first_seen_run == run.id)
    assert set(session.scalars(new_versions)) == ids_of(diff["added"]) | ids_of(diff["modified"])
    for external_id in ids_of(diff["modified"]):
        versions = session.scalars(
            select(SourceRecord).where(SourceRecord.external_id == external_id)
        ).all()
        assert sorted(v.valid_to is None for v in versions) == [False, True]
    # Incremental runs cannot see deletions; the deleted records stay current.
    assert ids_of(diff["removed"]) <= current_ids(session)
    session.refresh(source)
    assert source.workspace_watermarks != before


def test_full_sync_after_the_demo_mutation_marks_deleted_records_removed(session, sync, fixtures):
    # Arrange
    sync(full=True)
    diff = apply_set(fixtures, DEMO)["tenants"][SLUG]

    # Act
    run = sync(full=True)

    # Assert
    removed = ids_of(diff["removed"])
    assert run.counts["removed"] == len(removed)
    closed = select(SourceRecord.external_id).where(SourceRecord.removed_run == run.id)
    assert set(session.scalars(closed)) == removed
    assert not removed & current_ids(session)


@pytest.mark.parametrize("full", [False, True])
def test_running_the_same_sync_twice_creates_no_new_versions(session, sync, full):
    # Arrange
    sync(full=True)
    versions = version_count(session)

    # Act
    run = sync(full=full)

    # Assert
    assert run.status == "succeeded"
    assert (run.counts["new"], run.counts["changed"], run.counts["removed"]) == (0, 0, 0)
    assert version_count(session) == versions


def test_a_failed_run_is_recorded_and_leaves_the_previous_data_intact(
    session, source, sync, fixtures
):
    # Arrange
    sync(full=True)
    session.refresh(source)
    watermarks = dict(source.workspace_watermarks)
    versions = version_count(session)
    diff = apply_set(fixtures, DEMO)["tenants"][SLUG]

    def failing_detector(*_):
        raise RuntimeError("change detection broke")

    # Act
    failed = sync(detect_changes=failing_detector)

    # Assert
    assert failed.status == "failed"
    assert failed.error == "RuntimeError: change detection broke"
    assert failed.finished_at is not None
    assert failed.counts["fetched"] > 0
    assert failed.counts["new"] == failed.counts["changed"] == 0
    assert version_count(session) == versions
    session.refresh(source)
    assert source.workspace_watermarks == watermarks
    # The raw payloads stay archived, for reprocessing.
    archived = select(func.count()).where(RawRecordRow.sync_run_id == failed.id)
    assert session.scalar(archived) == failed.counts["fetched"]

    # The watermark did not move, so the next run still finds every change.
    retried = sync()
    assert retried.counts["new"] == len(ids_of(diff["added"]))
    assert retried.counts["changed"] == len(ids_of(diff["modified"]))


def test_a_rejected_api_key_fails_the_run_without_storing_anything(session, sync, mock_app):
    # Arrange
    with mock_client(mock_app, "unknown-tenant") as rejected:
        # Act
        run = sync(full=True, client=rejected)

    # Assert
    assert run.status == "failed"
    assert run.error.startswith("OmerloAuthError")
    assert "401" in run.error
    assert run.counts["fetched"] == 0
    assert version_count(session) == 0


def test_change_detection_gets_the_run_outcome_after_the_versions_are_stored(
    session, sync, fixtures
):
    # Arrange
    sync(full=True)
    diff = apply_set(fixtures, DEMO)["tenants"][SLUG]
    calls = []

    def detector(detector_session, run, upserted, removed):
        stored = select(func.count()).where(SourceRecord.first_seen_run == run.id)
        calls.append((run.id, set(upserted.added), removed, detector_session.scalar(stored)))

    # Act
    run = sync(full=True, detect_changes=detector)

    # Assert
    [(run_id, added, removed, stored)] = calls
    assert run_id == run.id
    assert added == ids_of(diff["added"])
    assert set(removed) == ids_of(diff["removed"])
    assert stored == len(ids_of(diff["added"]) | ids_of(diff["modified"]))


def test_sync_command_runs_a_seeded_mock_source(
    migrated_database, mock_app, tmp_path, monkeypatch, capsys
):
    # Arrange
    with Session(migrated_database) as setup:
        seed(setup)
        setup.commit()
    monkeypatch.setenv("ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setattr(
        sync_command, "create_omerlo_client", lambda settings: mock_client(mock_app, SLUG)
    )

    # Act
    sync_command.main(["--tenant", SLUG, "--full"])
    sync_command.main(["--tenant", SLUG])

    # Assert
    lines = capsys.readouterr().out.splitlines()
    full, incremental = [line for line in lines if line.startswith("Sync run")]
    assert "(full) succeeded" in full
    assert "(incremental) succeeded" in incremental
    assert "new 0, changed 0" in incremental


def test_sync_command_exits_with_an_error_when_the_run_fails(
    migrated_database, mock_app, tmp_path, monkeypatch
):
    # Arrange
    with Session(migrated_database) as setup:
        seed(setup)
        setup.commit()
    monkeypatch.setenv("ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setattr(
        sync_command, "create_omerlo_client", lambda settings: mock_client(mock_app, "nobody")
    )

    # Act / Assert
    with pytest.raises(SystemExit) as exit_info:
        sync_command.main(["--tenant", SLUG])
    assert exit_info.value.code == 1


def test_sync_command_rejects_an_unknown_tenant(migrated_database, capsys):
    # Act
    with pytest.raises(SystemExit) as exit_info:
        sync_command.main(["--tenant", "nobody"])

    # Assert
    assert exit_info.value.code == 2
    assert "No tenant 'nobody'" in capsys.readouterr().err
