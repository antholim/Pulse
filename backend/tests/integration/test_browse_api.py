"""The sync runs page endpoints, over two real sync runs against the mock server."""

# The sync fixtures are imported from test_sync_runs; pytest injects them by name.
# ruff: noqa: F811

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.browse import database
from app.main import app
from app.models import Tenant
from synthetic.mutate import DEMO, apply_set
from tests.integration.test_sync_runs import (  # noqa: F401
    SLUG,
    archive,
    client,
    fixtures,
    mock_app,
    source,
    sync,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def api(session):
    app.dependency_overrides[database] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def two_runs(sync, fixtures):
    first = sync(full=True)
    diff = apply_set(fixtures, DEMO)["tenants"][SLUG]
    second = sync()
    return first, second, diff


def modified_organization(diff) -> str:
    return next(e["id"] for e in diff["modified"] if e["kind"] == "organizations")


def test_tenants_are_listed_with_their_slug(api, source):
    # Act
    tenants = api.get("/api/tenants").json()

    # Assert
    assert {"id": str(source.tenant_id), "name": "Média démo Capitale", "slug": SLUG} in tenants


def test_runs_are_listed_newest_first_with_their_counts(api, source, two_runs):
    # Arrange
    first, second, _ = two_runs

    # Act
    runs = api.get(f"/api/tenants/{source.tenant_id}/runs").json()

    # Assert
    assert [r["id"] for r in runs] == [str(second.id), str(first.id)]
    assert [r["mode"] for r in runs] == ["incremental", "full"]
    assert runs[0]["status"] == "succeeded"
    assert runs[0]["counts"]["changes"] == second.counts["changes"]


def test_run_changes_match_the_recorded_counts_and_carry_field_diffs(api, source, two_runs):
    # Arrange
    _, second, diff = two_runs
    org_id = modified_organization(diff)

    # Act
    changes = api.get(f"/api/tenants/{source.tenant_id}/runs/{second.id}/changes").json()

    # Assert
    by_type = {t: [c for c in changes if c["change_type"] == t] for t in ("added", "modified")}
    assert len(by_type["added"]) == second.counts["changes"]["added"]
    assert len(by_type["modified"]) == second.counts["changes"]["modified"]
    org = next(c for c in changes if c["external_id"] == org_id)
    assert org["kind"] == "organization"
    assert org["label"]
    assert all({"before", "after"} <= set(v) for v in org["changed_fields"].values())


def test_record_history_shows_each_version_with_its_change(api, source, two_runs):
    # Arrange
    first, second, diff = two_runs
    org_id = modified_organization(diff)

    # Act
    history = api.get(f"/api/tenants/{source.tenant_id}/records/{source.id}/{org_id}").json()

    # Assert
    old, new = history["versions"]
    assert old["valid_to"] is not None
    assert new["valid_to"] is None
    assert [e["change_type"] for e in old["events"]] == ["added"]
    assert [(e["change_type"], e["sync_run_id"]) for e in new["events"]] == [
        ("modified", str(second.id))
    ]
    assert old["events"][0]["sync_run_id"] == str(first.id)


def test_records_can_be_searched_by_name(api, source, two_runs):
    # Arrange
    org = api.get(f"/api/tenants/{source.tenant_id}/records", params={"kind": "organization"})
    name = org.json()[0]["label"]

    # Act
    found = api.get(
        f"/api/tenants/{source.tenant_id}/records", params={"q": name[:8], "kind": "organization"}
    ).json()

    # Assert
    assert name in [r["label"] for r in found]


def test_another_tenant_cannot_read_a_run(api, session, source, two_runs):
    # Arrange
    _, second, _ = two_runs
    other = Tenant(name="Other", omerlo_media_id="other")
    session.add(other)
    session.flush()

    # Act
    response = api.get(f"/api/tenants/{other.id}/runs/{second.id}/changes")

    # Assert
    assert response.status_code == 404


def test_unknown_tenant_gets_404(api):
    # Act / Assert
    assert api.get(f"/api/tenants/{uuid.uuid4()}/runs").status_code == 404
