"""Versioned upsert and as-of query against a real database."""

import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ingestion.omerlo.mapping.mappers import MappedRecord
from app.models import (
    MatchCandidate,
    Organization,
    OrgLink,
    Source,
    SourceRecord,
    SyncRun,
    Tenant,
)
from app.services.source_records import close_unseen, upsert_records, version_as_of

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


def add_source(session: Session, name: str = "Tenant A") -> Source:
    tenant = Tenant(name=name)
    session.add(tenant)
    session.flush()
    source = Source(tenant_id=tenant.id, kind="mock")
    session.add(source)
    session.flush()
    return source


@pytest.fixture
def source(session):
    return add_source(session)


@pytest.fixture
def runs(session, source):
    return Runs(session, source)


def org(external_id: str = "org-1", name: str = "groupe exemple", **attributes) -> MappedRecord:
    return MappedRecord(
        kind="organization",
        external_id=external_id,
        workspace_id="ws-1",
        name_normalized=name,
        domain="exemple.ca",
        attributes={"name": name, **attributes},
    )


def versions(session: Session, external_id: str = "org-1") -> list[SourceRecord]:
    statement = (
        select(SourceRecord)
        .where(SourceRecord.external_id == external_id)
        .order_by(SourceRecord.valid_from, SourceRecord.valid_to)
        .execution_options(populate_existing=True)
    )
    return list(session.scalars(statement))


def link(session: Session, record: SourceRecord) -> Organization:
    organization = Organization(tenant_id=record.tenant_id, display_name="Groupe Exemple")
    session.add(organization)
    session.flush()
    session.add(
        OrgLink(
            tenant_id=record.tenant_id,
            organization_id=organization.id,
            source_record_id=record.id,
            method="domain",
            confidence=0.9,
            decided_by="tier1:domain",
        )
    )
    session.flush()
    return organization


def pair(session: Session, first: SourceRecord, second: SourceRecord, status: str) -> None:
    left, right = sorted([first.id, second.id])
    session.add(
        MatchCandidate(
            tenant_id=first.tenant_id,
            left_record_id=left,
            right_record_id=right,
            score=0.8,
            matched_fields=["name"],
            status=status,
        )
    )
    session.flush()


def candidates(session: Session) -> set[tuple[str, str, str]]:
    """(left external id, right external id, status) for pairs of current versions."""
    rows = session.execute(
        select(MatchCandidate, SourceRecord.external_id)
        .join(SourceRecord, SourceRecord.id == MatchCandidate.left_record_id)
        .where(SourceRecord.valid_to.is_(None))
    )
    found = set()
    for candidate, left in rows:
        right = session.get(SourceRecord, candidate.right_record_id, populate_existing=True)
        if right.valid_to is None:
            found.add((*sorted([left, right.external_id]), candidate.status))
    return found


def test_a_new_record_starts_its_first_version(session, runs):
    # Arrange
    run = runs.next()

    # Act
    result = upsert_records(session, run, [org()])

    # Assert
    assert result.added == ["org-1"]
    [version] = versions(session)
    assert version.valid_from == run.started_at
    assert version.valid_to is None
    assert version.first_seen_run == version.last_seen_run == run.id
    assert version.removed_run is None
    assert version.content_hash


def test_an_unchanged_record_only_moves_last_seen_run(session, runs):
    # Arrange
    first, second = runs.next(), runs.next()
    upsert_records(session, first, [org(updated_at="2026-10-01")])

    # Act
    result = upsert_records(session, second, [org(updated_at="2026-10-02")])

    # Assert
    assert result.unchanged == ["org-1"]
    [version] = versions(session)
    assert version.first_seen_run == first.id
    assert version.last_seen_run == second.id
    assert version.valid_to is None


def test_a_changed_record_closes_its_version_and_opens_a_new_one(session, runs):
    # Arrange
    first, second = runs.next(), runs.next()
    upsert_records(session, first, [org()])

    # Act
    result = upsert_records(session, second, [org(name="groupe exemple inc")])

    # Assert
    assert result.changed == ["org-1"]
    old, new = versions(session)
    assert old.valid_to == second.started_at
    assert old.removed_run is None
    assert new.valid_from == second.started_at
    assert new.valid_to is None
    assert new.name_normalized == "groupe exemple inc"
    assert new.first_seen_run == new.last_seen_run == second.id


def test_a_new_version_keeps_the_organization_link_and_candidates(session, runs):
    # Arrange
    first, second = runs.next(), runs.next()
    upsert_records(session, first, [org("org-1"), org("org-2"), org("org-3")])
    one = version_as_of(session, first, "org-1")
    organization = link(session, one)
    pair(session, one, version_as_of(session, first, "org-2"), "rejected")
    pair(session, one, version_as_of(session, first, "org-3"), "accepted")

    # Act
    upsert_records(session, second, [org("org-1", name="nouveau nom")])

    # Assert
    new = version_as_of(session, second, "org-1")
    assert new.id != one.id
    copied = session.get(OrgLink, new.id)
    assert copied.organization_id == organization.id
    assert (copied.method, copied.confidence, copied.decided_by) == ("domain", 0.9, "tier1:domain")
    assert session.get(OrgLink, one.id) is not None
    assert candidates(session) == {("org-1", "org-2", "rejected"), ("org-1", "org-3", "accepted")}


def test_two_changes_in_a_row_keep_three_versions_found_by_run(session, runs):
    # Arrange
    first, second, third = runs.next(), runs.next(), runs.next()
    upsert_records(session, first, [org(name="nom un")])
    link(session, version_as_of(session, first, "org-1"))

    # Act
    upsert_records(session, second, [org(name="nom deux")])
    upsert_records(session, third, [org(name="nom trois")])

    # Assert
    one, two, three = versions(session)
    assert (one.valid_to, two.valid_from) == (second.started_at, second.started_at)
    assert (two.valid_to, three.valid_from) == (third.started_at, third.started_at)
    assert three.valid_to is None
    names = [version_as_of(session, run, "org-1").name_normalized for run in (first, second, third)]
    assert names == ["nom un", "nom deux", "nom trois"]
    assert all(session.get(OrgLink, version.id) for version in (one, two, three))


def test_the_as_of_query_finds_nothing_before_the_first_version(session, runs):
    # Arrange
    before, first = runs.next(), runs.next()
    upsert_records(session, first, [org()])

    # Act
    found = version_as_of(session, before, "org-1")

    # Assert
    assert found is None


def test_a_record_missing_from_a_full_sync_is_closed_and_marked_removed(session, runs):
    # Arrange
    first, second = runs.next(), runs.next()
    upsert_records(session, first, [org("org-1"), org("org-2")])
    upsert_records(session, second, [org("org-2")])

    # Act
    removed = close_unseen(session, second)

    # Assert
    assert removed == ["org-1"]
    [version] = versions(session, "org-1")
    assert version.valid_to == second.started_at
    assert version.removed_run == second.id
    assert version_as_of(session, first, "org-1") is not None
    assert version_as_of(session, second, "org-1") is None
    assert version_as_of(session, second, "org-2") is not None


def test_a_removed_record_that_reappears_gets_a_new_version_with_its_link(session, runs):
    # Arrange
    first, second, third = runs.next(), runs.next(), runs.next()
    upsert_records(session, first, [org()])
    organization = link(session, version_as_of(session, first, "org-1"))
    close_unseen(session, second)

    # Act
    result = upsert_records(session, third, [org()])

    # Assert
    assert result.added == ["org-1"]
    removed, back = versions(session)
    assert removed.removed_run == second.id
    assert back.valid_from == third.started_at
    assert back.valid_to is None
    assert back.removed_run is None
    assert session.get(OrgLink, back.id).organization_id == organization.id
    assert version_as_of(session, second, "org-1") is None


def test_records_fetched_but_not_mapped_are_not_taken_for_removed(session, runs):
    # Arrange
    first, second = runs.next(), runs.next()
    upsert_records(session, first, [org("org-1"), org("org-2")])

    # Act
    removed = close_unseen(session, second, keep=["org-1"])

    # Assert
    assert removed == ["org-2"]
    assert versions(session, "org-1")[0].valid_to is None


def test_removal_only_closes_records_of_the_runs_own_source(session, runs):
    # Arrange
    other = Runs(session, add_source(session, "Tenant B"))
    other_run = other.next()
    upsert_records(session, other_run, [org("org-1")])
    run = runs.next()

    # Act
    removed = close_unseen(session, run)

    # Assert
    assert removed == []
    assert version_as_of(session, other_run, "org-1").valid_to is None


def test_a_candidate_between_two_changed_records_moves_once(session, runs):
    # Arrange
    first, second = runs.next(), runs.next()
    upsert_records(session, first, [org("org-1"), org("org-2")])
    pair(
        session,
        version_as_of(session, first, "org-1"),
        version_as_of(session, first, "org-2"),
        "accepted",
    )

    # Act: one batch per record, so each side moves in a different statement.
    upsert_records(
        session, second, [org("org-1", name="un"), org("org-2", name="deux")], batch_size=1
    )

    # Assert
    assert candidates(session) == {("org-1", "org-2", "accepted")}
    current = [version_as_of(session, second, key).id for key in ("org-1", "org-2")]
    between_current = select(func.count()).where(
        MatchCandidate.left_record_id.in_(current), MatchCandidate.right_record_id.in_(current)
    )
    assert session.scalar(between_current) == 1


def test_the_last_copy_of_a_record_in_one_run_wins(session, runs):
    # Arrange
    run = runs.next()

    # Act
    result = upsert_records(session, run, [org(name="premier"), org(name="dernier")])

    # Assert
    assert result.added == ["org-1"]
    [version] = versions(session)
    assert version.name_normalized == "dernier"


def test_a_thousand_records_sync_in_seconds(session, runs):
    # Arrange
    first, second = runs.next(), runs.next()
    records = [org(f"org-{n}", name=f"organisation {n}", city="quebec") for n in range(1000)]
    changed = [replace(r, name_normalized=f"{r.name_normalized} inc") for r in records[::2]]

    # Act
    started = time.perf_counter()
    upsert_records(session, first, records)
    result = upsert_records(session, second, changed + records[1::2])
    elapsed = time.perf_counter() - started

    # Assert
    assert (len(result.changed), len(result.unchanged)) == (500, 500)
    assert session.scalar(select(func.count()).select_from(SourceRecord)) == 1500
    assert elapsed < 10
