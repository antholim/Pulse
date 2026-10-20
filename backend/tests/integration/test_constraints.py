"""The database itself enforces the tenancy and versioning rules of data model v1."""

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    MatchCandidate,
    Organization,
    OrgLink,
    RecordChange,
    Source,
    SourceRecord,
    SyncRun,
    Tenant,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class TenantRows:
    tenant: Tenant
    source: Source
    run: SyncRun


def add_tenant(session: Session, name: str) -> TenantRows:
    tenant = Tenant(name=name)
    session.add(tenant)
    session.flush()
    source = Source(tenant_id=tenant.id, kind="mock")
    session.add(source)
    session.flush()
    run = SyncRun(tenant_id=tenant.id, source_id=source.id)
    session.add(run)
    session.flush()
    return TenantRows(tenant, source, run)


def new_version(rows: TenantRows, external_id: str, **fields) -> SourceRecord:
    return SourceRecord(
        tenant_id=rows.tenant.id,
        source_id=rows.source.id,
        external_id=external_id,
        kind="organization",
        first_seen_run=rows.run.id,
        last_seen_run=rows.run.id,
        **fields,
    )


def add_record(session: Session, rows: TenantRows, external_id: str, **fields) -> SourceRecord:
    record = new_version(rows, external_id, **fields)
    session.add(record)
    session.flush()
    return record


def rejected(session: Session, row) -> bool:
    """Insert `row` in a savepoint; True when the database rejects it."""
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        return True
    return False


@pytest.fixture
def tenant_a(session):
    return add_tenant(session, "Tenant A")


@pytest.fixture
def tenant_b(session):
    return add_tenant(session, "Tenant B")


def test_a_full_tenant_graph_can_be_stored(session, tenant_a):
    first = add_record(session, tenant_a, "org-1", name_normalized="groupe exemple")
    second = add_record(session, tenant_a, "org-2")
    organization = Organization(tenant_id=tenant_a.tenant.id, display_name="Groupe Exemple")
    session.add(organization)
    session.flush()
    left, right = sorted([first.id, second.id])

    assert not rejected(
        session,
        OrgLink(
            tenant_id=tenant_a.tenant.id,
            organization_id=organization.id,
            source_record_id=first.id,
            method="domain",
            confidence=1.0,
            decided_by="tier1:domain",
        ),
    )
    assert not rejected(
        session,
        MatchCandidate(
            tenant_id=tenant_a.tenant.id, left_record_id=left, right_record_id=right, score=0.7
        ),
    )
    assert not rejected(
        session,
        RecordChange(
            tenant_id=tenant_a.tenant.id,
            sync_run_id=tenant_a.run.id,
            source_record_id=first.id,
            change_type="added",
        ),
    )


def test_tenant_id_is_required(session):
    assert rejected(session, Organization(display_name="No tenant"))


def test_a_sync_run_cannot_use_another_tenants_source(session, tenant_a, tenant_b):
    assert rejected(session, SyncRun(tenant_id=tenant_b.tenant.id, source_id=tenant_a.source.id))


def test_an_organization_link_cannot_cross_tenants(session, tenant_a, tenant_b):
    record = add_record(session, tenant_b, "org-1")
    organization = Organization(tenant_id=tenant_a.tenant.id, display_name="Tenant A org")
    session.add(organization)
    session.flush()

    for tenant in (tenant_a, tenant_b):
        assert rejected(
            session,
            OrgLink(
                tenant_id=tenant.tenant.id,
                organization_id=organization.id,
                source_record_id=record.id,
                method="manual",
                confidence=1.0,
                decided_by="test",
            ),
        )


def test_a_match_candidate_cannot_pair_records_of_two_tenants(session, tenant_a, tenant_b):
    left, right = sorted(
        [add_record(session, tenant_a, "org-1").id, add_record(session, tenant_b, "org-1").id]
    )

    assert rejected(
        session,
        MatchCandidate(
            tenant_id=tenant_a.tenant.id, left_record_id=left, right_record_id=right, score=0.5
        ),
    )


def october(day: int) -> datetime:
    return datetime(2026, 10, day, tzinfo=UTC)


def test_only_one_current_version_per_record(session, tenant_a):
    add_record(session, tenant_a, "org-1")

    assert rejected(session, new_version(tenant_a, "org-1"))


def test_closed_versions_sit_next_to_the_current_one(session, tenant_a):
    add_record(session, tenant_a, "org-1", valid_from=october(1), valid_to=october(5))
    add_record(session, tenant_a, "org-1", valid_from=october(5), valid_to=october(10))

    assert not rejected(session, new_version(tenant_a, "org-1", valid_from=october(10)))


@pytest.mark.parametrize(
    ("valid_from", "valid_to"),
    [(october(1), october(5)), (october(3), october(8)), (october(4), None)],
    ids=["same range", "partial overlap", "current version overlaps"],
)
def test_versions_of_a_record_cannot_overlap(session, tenant_a, valid_from, valid_to):
    add_record(session, tenant_a, "org-1", valid_from=october(1), valid_to=october(5))

    assert rejected(
        session, new_version(tenant_a, "org-1", valid_from=valid_from, valid_to=valid_to)
    )


def test_versions_of_different_records_can_overlap(session, tenant_a):
    add_record(session, tenant_a, "org-1", valid_from=october(1), valid_to=october(5))

    assert not rejected(
        session, new_version(tenant_a, "org-2", valid_from=october(1), valid_to=october(5))
    )


def test_the_same_external_id_can_be_current_in_two_tenants(session, tenant_a, tenant_b):
    add_record(session, tenant_a, "org-1")

    assert not rejected(session, new_version(tenant_b, "org-1"))


@pytest.mark.parametrize(
    "make_row",
    [
        lambda session, rows: Source(tenant_id=rows.tenant.id, kind="ftp"),
        lambda session, rows: SyncRun(
            tenant_id=rows.tenant.id, source_id=rows.source.id, status="done"
        ),
        lambda session, rows: RecordChange(
            tenant_id=rows.tenant.id,
            sync_run_id=rows.run.id,
            source_record_id=add_record(session, rows, "org-1").id,
            change_type="renamed",
        ),
    ],
    ids=["source kind", "sync run status", "change type"],
)
def test_values_outside_the_allowed_lists_are_rejected(session, tenant_a, make_row):
    assert rejected(session, make_row(session, tenant_a))


def test_a_match_candidate_pair_is_stored_once_in_one_order(session, tenant_a):
    left, right = sorted(
        [add_record(session, tenant_a, "org-1").id, add_record(session, tenant_a, "org-2").id]
    )

    def candidate(first, second):
        return MatchCandidate(
            tenant_id=tenant_a.tenant.id, left_record_id=first, right_record_id=second, score=0.6
        )

    assert not rejected(session, candidate(left, right))
    assert rejected(session, candidate(left, right))
    assert rejected(session, candidate(right, left))
