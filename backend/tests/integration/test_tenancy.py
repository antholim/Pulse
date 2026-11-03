# AI contribution: 50% or more AI-generated
"""A TenantSession only ever reads and writes the rows of the tenant it is bound to."""

from dataclasses import dataclass

import pytest
from sqlalchemy import func, insert, inspect, select, text, update
from sqlalchemy.exc import NoResultFound

from app.core.tenancy import (
    TenantContextError,
    TenantSession,
    bound_to_tenant,
    system_access,
    tenant_owned,
)
from app.models import (
    MatchCandidate,
    Organization,
    OrgLink,
    RawRecord,
    RecordChange,
    Source,
    SourceRecord,
    SyncRun,
    Tenant,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class Graph:
    """One row in every table of one tenant."""

    tenant: Tenant
    rows: dict[type, object]


def add_graph(session, name: str) -> Graph:
    tenant = Tenant(name=name)
    session.add(tenant)
    session.flush()
    tid = tenant.id
    source = Source(tenant_id=tid, kind="mock")
    session.add(source)
    session.flush()
    run = SyncRun(tenant_id=tid, source_id=source.id)
    session.add(run)
    session.flush()
    first, second = (
        SourceRecord(
            tenant_id=tid,
            source_id=source.id,
            external_id=external_id,
            kind="organization",
            first_seen_run=run.id,
            last_seen_run=run.id,
        )
        for external_id in ("org-1", "org-2")
    )
    organization = Organization(tenant_id=tid, display_name=f"{name} inc.")
    session.add_all([first, second, organization])
    session.flush()
    left, right = sorted([first.id, second.id])
    rows = {
        Source: source,
        SyncRun: run,
        SourceRecord: first,
        Organization: organization,
        RawRecord: RawRecord(
            tenant_id=tid,
            sync_run_id=run.id,
            external_id="org-1",
            entity_kind="organization",
            payload_uri=f"file://{name}",
            payload_hash="0" * 64,
        ),
        RecordChange: RecordChange(
            tenant_id=tid, sync_run_id=run.id, source_record_id=first.id, change_type="added"
        ),
        OrgLink: OrgLink(
            tenant_id=tid,
            organization_id=organization.id,
            source_record_id=first.id,
            method="domain",
            confidence=1.0,
            decided_by="tier1:domain",
        ),
        MatchCandidate: MatchCandidate(
            tenant_id=tid, left_record_id=left, right_record_id=right, score=0.7
        ),
    }
    session.add_all(rows.values())
    session.flush()
    return Graph(tenant, rows)


@pytest.fixture
def tenant_a(session):
    return add_graph(session, "Tenant A")


@pytest.fixture
def tenant_b(session):
    return add_graph(session, "Tenant B")


@pytest.fixture
def unscoped(session):
    """A second app session on the same transaction, with no tenant and no system access."""
    other = TenantSession(bind=session.connection())
    yield other
    other.close()


def test_the_graph_has_a_row_in_every_tenant_owned_table():
    # Act / Assert: a new table must be added to add_graph, so the isolation tests cover it.
    assert set(tenant_owned()) == {
        Source,
        SyncRun,
        SourceRecord,
        Organization,
        RawRecord,
        RecordChange,
        OrgLink,
        MatchCandidate,
    }


@pytest.mark.parametrize("model", tenant_owned(), ids=lambda m: m.__name__)
def test_reads_return_only_the_bound_tenants_rows(session, tenant_a, tenant_b, model):
    # Act
    with bound_to_tenant(session, tenant_a.tenant.id):
        rows = session.scalars(select(model)).all()

    # Assert
    assert rows
    assert {row.tenant_id for row in rows} == {tenant_a.tenant.id}


@pytest.mark.parametrize("model", tenant_owned(), ids=lambda m: m.__name__)
def test_another_tenants_id_cannot_be_fetched(session, tenant_a, tenant_b, model):
    # Arrange: B's rows are in the identity map, so get() could answer without SQL.
    row = tenant_b.rows[model]
    guessed = inspect(row).identity
    key = [
        column == value for column, value in zip(inspect(model).primary_key, guessed, strict=True)
    ]

    # Act
    with bound_to_tenant(session, tenant_a.tenant.id):
        found = session.get(model, guessed)
        by_query = session.scalar(select(model).where(*key))

    # Assert
    assert found is None
    assert by_query is None


def test_get_one_raises_for_another_tenants_id(session, tenant_a, tenant_b):
    # Act / Assert
    with bound_to_tenant(session, tenant_a.tenant.id), pytest.raises(NoResultFound):
        session.get_one(SyncRun, tenant_b.rows[SyncRun].id)


def test_only_the_bound_tenant_is_visible(session, tenant_a, tenant_b):
    # Act
    with bound_to_tenant(session, tenant_a.tenant.id):
        tenants = session.scalars(select(Tenant)).all()
        other = session.get(Tenant, tenant_b.tenant.id)

    # Assert
    assert tenants == [tenant_a.tenant]
    assert other is None


def test_counts_and_joins_are_scoped(session, tenant_a, tenant_b):
    # Act
    with bound_to_tenant(session, tenant_a.tenant.id):
        count = session.scalar(select(func.count(SourceRecord.id)))
        joined = session.execute(
            select(RecordChange, SourceRecord).join(
                SourceRecord, SourceRecord.id == RecordChange.source_record_id
            )
        ).all()

    # Assert
    assert count == 2
    assert [change.tenant_id for change, _ in joined] == [tenant_a.tenant.id]


def test_updates_and_deletes_only_touch_the_bound_tenant(session, tenant_a, tenant_b):
    # Act
    with bound_to_tenant(session, tenant_a.tenant.id):
        session.execute(update(Organization).values(display_name="Renamed"))
        session.execute(
            update(MatchCandidate).values(status="rejected"),
            execution_options={"synchronize_session": False},
        )

    # Assert
    with system_access(session):
        rows = session.execute(select(Organization.tenant_id, Organization.display_name))
        names = dict(rows.tuples().all())
    assert names == {tenant_a.tenant.id: "Renamed", tenant_b.tenant.id: "Tenant B inc."}


def test_a_session_without_a_tenant_cannot_query(unscoped, tenant_a):
    # Act / Assert
    with pytest.raises(TenantContextError, match="No tenant"):
        unscoped.scalars(select(SyncRun)).all()
    with pytest.raises(TenantContextError, match="No tenant"):
        unscoped.execute(text("SELECT 1"))
    with pytest.raises(TenantContextError, match="No tenant"):
        unscoped.get(Tenant, tenant_a.tenant.id)


def test_a_session_without_a_tenant_cannot_write(unscoped, tenant_a):
    # Arrange
    unscoped.add(Organization(tenant_id=tenant_a.tenant.id, display_name="Unscoped"))

    # Act / Assert
    with pytest.raises(TenantContextError, match="No tenant"):
        unscoped.flush()


def test_new_rows_get_the_bound_tenant(session, tenant_a):
    # Arrange
    organization = Organization(display_name="No tenant given")

    # Act
    with bound_to_tenant(session, tenant_a.tenant.id):
        session.add(organization)
        session.flush()

    # Assert
    assert organization.tenant_id == tenant_a.tenant.id


def test_a_row_of_another_tenant_cannot_be_added(session, tenant_a, tenant_b):
    # Arrange
    stray = Organization(tenant_id=tenant_b.tenant.id, display_name="Stray")

    # Act / Assert
    with bound_to_tenant(session, tenant_a.tenant.id):
        session.add(stray)
        with pytest.raises(TenantContextError, match="another tenant"):
            session.flush()
        session.expunge(stray)


def test_a_tenant_cannot_be_created_inside_a_tenant(session, tenant_a):
    # Act / Assert
    with bound_to_tenant(session, tenant_a.tenant.id):
        session.add(Tenant(name="Nested"))
        with pytest.raises(TenantContextError, match="system access"):
            session.flush()
        session.rollback()


def test_a_row_cannot_move_to_another_tenant(session, tenant_a, tenant_b):
    # Act / Assert
    with bound_to_tenant(session, tenant_a.tenant.id):
        organization = session.get(Organization, tenant_a.rows[Organization].id)
        organization.tenant_id = tenant_b.tenant.id
        with pytest.raises(TenantContextError, match="move"):
            session.flush()
        session.rollback()


def test_raw_sql_must_pass_the_bound_tenant(session, tenant_a, tenant_b):
    # Arrange
    query = text("SELECT count(*) FROM organization WHERE tenant_id = :tenant_id")

    # Act / Assert
    with bound_to_tenant(session, tenant_a.tenant.id):
        assert session.scalar(query, {"tenant_id": tenant_a.tenant.id}) == 1
        with pytest.raises(TenantContextError, match="another tenant"):
            session.scalar(query, {"tenant_id": tenant_b.tenant.id})
        with pytest.raises(TenantContextError, match="as a parameter"):
            session.scalar(text("SELECT count(*) FROM organization"))


def test_bulk_inserts_must_carry_the_bound_tenant(session, tenant_a, tenant_b):
    # Arrange
    row = {"display_name": "Bulk", "tenant_id": tenant_b.tenant.id}

    # Act / Assert
    with bound_to_tenant(session, tenant_a.tenant.id), pytest.raises(TenantContextError):
        session.execute(insert(Organization), [row])


def test_a_bound_session_cannot_switch_tenant_or_get_system_access(session, tenant_a, tenant_b):
    # Act / Assert
    with bound_to_tenant(session, tenant_a.tenant.id):
        with pytest.raises(TenantContextError, match="another tenant"):
            bound_to_tenant(session, tenant_b.tenant.id).__enter__()
        with pytest.raises(TenantContextError, match="system access"):
            system_access(session).__enter__()


def test_the_previous_scope_comes_back_after_the_block(session, tenant_a, tenant_b):
    # Act
    with bound_to_tenant(session, tenant_a.tenant.id):
        pass
    tenants = session.scalars(select(Tenant)).all()

    # Assert: the fixture session has system access again.
    assert {t.id for t in tenants} >= {tenant_a.tenant.id, tenant_b.tenant.id}


def test_a_statement_without_an_orm_entity_is_refused(session, tenant_a):
    # Act / Assert: select_from() alone hides the entity, so the filter cannot be added.
    with (
        bound_to_tenant(session, tenant_a.tenant.id),
        pytest.raises(TenantContextError, match="as a parameter"),
    ):
        session.scalar(select(func.count()).select_from(SourceRecord))
