"""Change detection against a real database, driven by the fixture mutation script."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.omerlo.mapping.mappers import MappedRecord
from app.models import RecordChange, Source, SourceRecord, SyncRun, Tenant
from app.services.record_changes import diff_runs, record_changes
from app.services.source_records import close_unseen, upsert_records
from synthetic.mutate import DEMO, mutate
from synthetic.omerlo_fixtures import OmerloFixtureGenerator
from tests.fixture_diff import assert_fields_correspond, expected, mapped_records
from tests.synthetic.conftest import SMALL

pytestmark = pytest.mark.integration

START = datetime(2026, 10, 1, tzinfo=UTC)


class Runs:
    """Sync runs of one source, each a day after the previous one."""

    def __init__(self, session: Session, source: Source):
        self.session, self.source, self.count = session, source, 0

    def next(self) -> SyncRun:
        self.count += 1
        run = SyncRun(
            tenant_id=self.source.tenant_id,
            source_id=self.source.id,
            started_at=START + timedelta(days=self.count),
        )
        self.session.add(run)
        self.session.flush()
        return run

    def sync(self, records: list[MappedRecord], *, full: bool = True) -> SyncRun:
        """A run that stores `records`, closes unseen ones when full, and records changes."""
        run = self.next()
        upsert_records(self.session, run, records)
        if full:
            close_unseen(self.session, run)
        record_changes(self.session, run)
        return run


def add_runs(session: Session, name: str = "Tenant A") -> Runs:
    tenant = Tenant(name=name)
    session.add(tenant)
    session.flush()
    source = Source(tenant_id=tenant.id, kind="mock")
    session.add(source)
    session.flush()
    return Runs(session, source)


@pytest.fixture
def runs(session):
    return add_runs(session)


def org(external_id: str = "org-1", name: str = "groupe exemple", **attributes) -> MappedRecord:
    return MappedRecord(
        kind="organization",
        external_id=external_id,
        workspace_id="ws-1",
        name_normalized=name,
        attributes={"name": name, **attributes},
    )


def rows(session: Session, run: SyncRun) -> dict[tuple[str, str], tuple[str, dict]]:
    """(kind, external id) to (change type, changed fields) for each change of `run`."""
    statement = (
        select(SourceRecord.kind, SourceRecord.external_id, RecordChange)
        .join(SourceRecord, SourceRecord.id == RecordChange.source_record_id)
        .where(RecordChange.sync_run_id == run.id)
    )
    return {
        (kind, external_id): (change.change_type, change.changed_fields)
        for kind, external_id, change in session.execute(statement)
    }


def of_type(found: dict, change_type: str) -> set[tuple[str, str]]:
    return {key for key, (kind, _) in found.items() if kind == change_type}


@pytest.fixture(scope="module")
def demo():
    before = OmerloFixtureGenerator(5, SMALL).generate()
    after, diff = mutate(before, DEMO)
    return before, after, diff


def test_the_first_run_adds_every_record(session, runs):
    # Act
    run = runs.sync([org("org-1"), org("org-2")])

    # Assert
    found = rows(session, run)
    assert found == {
        ("organization", "org-1"): ("added", {}),
        ("organization", "org-2"): ("added", {}),
    }
    assert run.counts == {"changes": {"added": 2, "modified": 0, "removed": 0}}


def test_a_modified_record_holds_its_changed_fields(session, runs):
    # Arrange
    runs.sync([org(city="quebec", updated_at="2026-10-01")])

    # Act
    run = runs.sync([org(name="nouveau nom", city="quebec", updated_at="2026-10-02")])

    # Assert
    assert rows(session, run) == {
        ("organization", "org-1"): (
            "modified",
            {
                "attributes.name": {"before": "groupe exemple", "after": "nouveau nom"},
                "name_normalized": {"before": "groupe exemple", "after": "nouveau nom"},
            },
        )
    }
    [change] = session.scalars(select(RecordChange).where(RecordChange.sync_run_id == run.id))
    current = session.scalars(select(SourceRecord).where(SourceRecord.valid_to.is_(None))).one()
    assert change.source_record_id == current.id


def test_an_updated_at_change_alone_is_not_a_change(session, runs):
    # Arrange
    runs.sync([org(updated_at="2026-10-01")])

    # Act
    run = runs.sync([org(updated_at="2026-10-02")])

    # Assert
    assert rows(session, run) == {}
    assert run.counts["changes"] == {"added": 0, "modified": 0, "removed": 0}


def test_a_removed_record_points_at_its_last_version_and_returns_as_added(session, runs):
    # Arrange
    runs.sync([org("org-1"), org("org-2")])

    # Act
    removing = runs.sync([org("org-2")])
    returning = runs.sync([org("org-1"), org("org-2")])

    # Assert
    assert rows(session, removing) == {("organization", "org-1"): ("removed", {})}
    assert rows(session, returning) == {("organization", "org-1"): ("added", {})}
    [removed] = session.scalars(select(RecordChange).where(RecordChange.sync_run_id == removing.id))
    version = session.get(SourceRecord, removed.source_record_id)
    assert version.removed_run == removing.id


def test_counts_keep_the_other_keys_and_a_second_call_replaces_the_rows(session, runs):
    # Arrange
    runs.sync([org()])
    run = runs.next()
    run.counts = {"fetched": 1}
    upsert_records(session, run, [org(name="autre")])
    record_changes(session, run)

    # Act
    counts = record_changes(session, run)

    # Assert
    assert counts == {"added": 0, "modified": 1, "removed": 0}
    assert run.counts == {"fetched": 1, "changes": counts}
    assert len(rows(session, run)) == 1


@pytest.mark.parametrize("tenant_index", [0, 1])
def test_a_full_sync_after_the_demo_set_finds_exactly_the_expected_diff(
    session, demo, tenant_index
):
    # Arrange
    before, after, diff = demo
    runs = add_runs(session)
    runs.sync(mapped_records(before[tenant_index]))
    wanted = expected(diff["tenants"][before[tenant_index].tenant.slug])

    # Act
    run = runs.sync(mapped_records(after[tenant_index]))

    # Assert
    found = rows(session, run)
    assert of_type(found, "added") == wanted.added
    assert of_type(found, "modified") == set(wanted.modified)
    assert of_type(found, "removed") == wanted.removed
    for key in wanted.modified:
        assert_fields_correspond(key[0], wanted.modified[key], found[key][1])
    assert run.counts["changes"] == {
        "added": len(wanted.added),
        "modified": len(wanted.modified),
        "removed": len(wanted.removed),
    }


def test_an_incremental_sync_after_the_demo_set_finds_adds_and_edits(session, demo):
    # Arrange
    before, after, diff = demo
    runs = add_runs(session)
    runs.sync(mapped_records(before[0]))
    wanted = expected(diff["tenants"][before[0].tenant.slug])
    changed = mapped_records(after[0], updated_after=diff["changed_after"])

    # Act
    run = runs.sync(changed, full=False)

    # Assert
    found = rows(session, run)
    assert of_type(found, "added") == wanted.added
    assert of_type(found, "modified") == set(wanted.modified)
    assert of_type(found, "removed") == set()
    for key in wanted.modified:
        assert_fields_correspond(key[0], wanted.modified[key], found[key][1])


def test_the_diff_between_two_runs_matches_the_recorded_changes(session, demo):
    # Arrange
    before, after, _ = demo
    runs = add_runs(session)
    first = runs.sync(mapped_records(before[0]))
    second = runs.sync(mapped_records(after[0]))

    # Act
    changes = diff_runs(session, first, second)
    backwards = diff_runs(session, second, first)

    # Assert
    recorded = rows(session, second)
    assert {(c.kind, c.external_id): (c.change_type, c.changed_fields) for c in changes} == (
        recorded
    )
    flipped = {"added": "removed", "removed": "added", "modified": "modified"}
    assert {(c.kind, c.external_id, c.change_type) for c in backwards} == {
        (kind, external_id, flipped[change_type])
        for (kind, external_id), (change_type, _) in recorded.items()
    }
    assert diff_runs(session, second, second) == []


def test_the_diff_across_several_runs_compares_the_end_states(session, runs):
    # Arrange
    first = runs.sync([org(name="un"), org("org-2"), org("org-3")])
    runs.sync([org(name="deux"), org("org-2")])
    third = runs.sync([org(name="trois"), org("org-2", name="autre"), org("org-4")])

    # Act
    changes = diff_runs(session, first, third)

    # Assert
    assert [(c.external_id, c.change_type) for c in changes] == [
        ("org-1", "modified"),
        ("org-2", "modified"),
        ("org-3", "removed"),
        ("org-4", "added"),
    ]
    assert changes[0].changed_fields["name_normalized"] == {"before": "un", "after": "trois"}


def test_runs_of_different_sources_cannot_be_compared(session, runs):
    # Arrange
    other = add_runs(session, "Tenant B")

    # Act, Assert
    with pytest.raises(ValueError, match="same source"):
        diff_runs(session, runs.next(), other.next())
