# AI contribution: 50% or more AI-generated
"""Two tenants synced from the mock server: nothing of one is reachable as the other.

Every service read and every tenant API endpoint is called as tenant A with tenant B's
ids, and the other way round.
"""

# The sync fixtures are imported from test_sync_runs; pytest injects them by name.
# ruff: noqa: F811

import uuid
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.browse import database
from app.core.errors import NotFoundError
from app.core.tenancy import bound_to_tenant
from app.ingestion.omerlo.connector import OmerloConnector
from app.main import app
from app.models import Source, SourceRecord, SyncRun, Tenant
from app.services import browse, record_changes, source_records
from app.services.sync_runs import run_sync
from app.storage.raw_records import read_run
from tests.integration.test_sync_runs import (  # noqa: F401
    Clock,
    archive,
    fixtures,
    mock_app,
    mock_client,
)

pytestmark = pytest.mark.integration

SLUGS = ("demo-capitale", "demo-estrie")
TENANT_ROUTES = {
    "/api/tenants/{tenant_id}/runs",
    "/api/tenants/{tenant_id}/runs/{run_id}/changes",
    "/api/tenants/{tenant_id}/records",
    "/api/tenants/{tenant_id}/records/{source_id}/{external_id}",
}


@dataclass(frozen=True)
class Synced:
    tenant: Tenant
    source: Source
    run: SyncRun
    external_ids: set[str]


@pytest.fixture
def synced(session, mock_app, archive) -> dict[str, Synced]:
    clock = Clock()
    result = {}
    for slug in SLUGS:
        tenant = Tenant(name=slug, omerlo_media_id=slug)
        session.add(tenant)
        session.flush()
        source = Source(tenant_id=tenant.id, kind="mock")
        session.add(source)
        session.commit()
        with mock_client(mock_app, slug) as client:
            run = run_sync(session, source, OmerloConnector(client), archive, full=True, now=clock)
        assert run.status == "succeeded"
        ids = set(
            session.scalars(
                select(SourceRecord.external_id).where(SourceRecord.tenant_id == tenant.id)
            )
        )
        result[slug] = Synced(tenant, source, run, ids)
    return result


@pytest.fixture(params=[SLUGS, SLUGS[::-1]], ids=["a-reads-b", "b-reads-a"])
def pair(request, synced) -> tuple[Synced, Synced]:
    """(reader, other): the tenant making the calls and the tenant it must not see."""
    reader, other = request.param
    return synced[reader], synced[other]


@pytest.fixture
def api(session):
    app.dependency_overrides[database] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def other_only_id(reader: Synced, other: Synced) -> str:
    """An external id that only the other tenant has, to search for and to guess."""
    return sorted(other.external_ids - reader.external_ids)[0]


def test_every_tenant_route_is_covered_here():
    # Act
    routes = {path for path in app.openapi()["paths"] if "{tenant_id}" in path}

    # Assert: a new tenant route must get an isolation check below.
    assert routes == TENANT_ROUTES


def test_both_tenants_have_data(synced):
    # Act / Assert
    assert all(s.external_ids for s in synced.values())


def test_runs_list_only_the_readers_runs(api, pair):
    # Arrange
    reader, _ = pair

    # Act
    runs = api.get(f"/api/tenants/{reader.tenant.id}/runs").json()

    # Assert
    assert [r["id"] for r in runs] == [str(reader.run.id)]
    assert {r["source_id"] for r in runs} == {str(reader.source.id)}


def test_another_tenants_run_is_not_found(api, pair):
    # Arrange
    reader, other = pair

    # Act
    response = api.get(f"/api/tenants/{reader.tenant.id}/runs/{other.run.id}/changes")

    # Assert
    assert response.status_code == 404


def test_search_finds_nothing_of_the_other_tenant(api, pair):
    # Arrange
    reader, other = pair
    guessed = other_only_id(reader, other)

    # Act
    everything = api.get(f"/api/tenants/{reader.tenant.id}/records").json()
    by_id = api.get(f"/api/tenants/{reader.tenant.id}/records", params={"q": guessed}).json()

    # Assert
    assert everything
    assert {r["source_id"] for r in everything} == {str(reader.source.id)}
    assert by_id == []


@pytest.mark.parametrize("source_of", ["other", "reader"])
def test_another_tenants_record_history_is_not_found(api, pair, source_of):
    # Arrange: guess the other tenant's record through its source or the reader's own.
    reader, other = pair
    source_id = (other if source_of == "other" else reader).source.id
    guessed = other_only_id(reader, other)

    # Act
    response = api.get(f"/api/tenants/{reader.tenant.id}/records/{source_id}/{guessed}")

    # Assert
    assert response.status_code == 404


def test_browse_services_see_nothing_of_the_other_tenant(session, pair):
    # Arrange: pass the other tenant's ids, as a bug in a route could.
    reader, other = pair
    tenant_id = other.tenant.id
    guessed = other_only_id(reader, other)

    # Act / Assert
    with bound_to_tenant(session, reader.tenant.id):
        assert browse.list_runs(session, tenant_id) == []
        assert browse.search_records(session, tenant_id) == []
        assert browse.run_order(session, {other.run.id}) == {}
        assert browse.list_tenants(session) == [reader.tenant]
        with pytest.raises(NotFoundError):
            browse.get_tenant(session, tenant_id)
        with pytest.raises(NotFoundError):
            browse.run_changes(session, tenant_id, other.run.id)
        with pytest.raises(NotFoundError):
            browse.record_history(session, tenant_id, other.source.id, guessed)


def test_sync_services_see_nothing_of_the_other_tenant(session, pair, archive):
    # Arrange
    reader, other = pair
    run = other.run
    guessed = other_only_id(reader, other)

    # Act / Assert
    with bound_to_tenant(session, reader.tenant.id):
        assert record_changes.run_changes(session, run) == []
        assert record_changes.version_ids(session, run) == {}
        assert source_records.latest_versions(session, run, [guessed]) == {}
        assert source_records.version_as_of(session, run, guessed) is None
        assert list(read_run(session, archive, other.tenant.id, run.id)) == []


def test_an_unknown_tenant_sees_nothing(api, synced):
    # Arrange
    unknown = uuid.uuid4()

    # Act / Assert
    assert api.get(f"/api/tenants/{unknown}/runs").status_code == 404
    assert api.get(f"/api/tenants/{unknown}/records").status_code == 404
