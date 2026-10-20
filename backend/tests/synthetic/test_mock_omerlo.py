import pytest

from synthetic.mock_omerlo import (
    CATEGORIES,
    COMMUNITY,
    COMMUNITY_KINDS,
    MAX_LIMIT,
    SORT_VALUES,
    WORKSPACES,
    api_key_for,
    build_app,
    encode_cursor,
)
from synthetic.omerlo_fixtures import OmerloFixtureGenerator, write_fixtures
from synthetic.omerlo_schema import MODELS, SUMMARY_MODELS
from tests.synthetic.conftest import SMALL


def list_path(workspace_id, kind):
    return f"{COMMUNITY}/workspaces/{workspace_id}/{kind}"


def fetch_all(client, path, headers, limit=7, **params):
    items, query = [], {"limit": limit, **params}
    while True:
        body = client.get(path, headers=headers, params=query).json()
        items += body["data"]
        if not body["meta"]["next"]:
            return items
        query = {"limit": limit, **params, "after": body["meta"]["next"]}


@pytest.fixture
def tenant(mock_tenants):
    return mock_tenants[0]


@pytest.fixture
def workspace_id(tenant):
    return tenant.resources["workspaces"][0]["id"]


@pytest.fixture
def orgs(workspace_id):
    return list_path(workspace_id, "organizations")


def in_workspace(tenant, kind, workspace_id):
    return [r for r in tenant.resources[kind] if r["profile"]["workspace_id"] == workspace_id]


# ------------------------------------------------------------------ access


def test_requests_without_a_valid_api_key_get_401(mock_omerlo, orgs):
    for headers in ({}, {"x-api-key": "nope"}):
        response = mock_omerlo.get(orgs, headers=headers)

        assert response.status_code == 401
        assert response.json() == {"error": "Unauthorized access"}


def test_api_key_query_parameter_is_accepted(mock_omerlo, orgs, tenant):
    response = mock_omerlo.get(orgs, params={"api_key": api_key_for(tenant.tenant.slug)})

    assert response.status_code == 200


def test_each_api_key_sees_only_its_tenant(mock_omerlo, mock_tenants, headers):
    other = mock_tenants[1]
    other_headers = {"x-api-key": api_key_for(other.tenant.slug)}
    other_org = other.resources["organizations"][0]

    first = {w["id"] for w in mock_omerlo.get(WORKSPACES, headers=headers).json()["data"]}
    second = {w["id"] for w in mock_omerlo.get(WORKSPACES, headers=other_headers).json()["data"]}

    assert first == {w["id"] for w in mock_tenants[0].resources["workspaces"]}
    assert not first & second
    detail = f"{COMMUNITY}/organizations/{other_org['id']}"
    assert mock_omerlo.get(detail, headers=headers).status_code == 404
    other_workspace = other.resources["workspaces"][0]["id"]
    workspace_list = list_path(other_workspace, "organizations")
    assert mock_omerlo.get(workspace_list, headers=headers).status_code == 404


# -------------------------------------------------------- composer, core


def test_workspaces_list_summaries_and_detail_has_statuses(mock_omerlo, headers, tenant):
    listed = mock_omerlo.get(WORKSPACES, headers=headers).json()["data"]

    for summary in listed:
        SUMMARY_MODELS["workspaces"].model_validate(summary)
    workspace = tenant.resources["workspaces"][0]
    detail = mock_omerlo.get(f"{WORKSPACES}/{workspace['id']}", headers=headers).json()
    assert detail["data"] == workspace
    assert detail["data"]["statuses"]


def test_categories_are_listed_in_full_and_readable_by_id(mock_omerlo, headers, tenant):
    categories = fetch_all(mock_omerlo, CATEGORIES, headers, limit=5)

    assert categories == sorted(
        tenant.resources["categories"], key=lambda c: (c["inserted_at"], c["id"])
    )
    first = categories[0]
    assert mock_omerlo.get(f"{CATEGORIES}/{first['id']}", headers=headers).json()["data"] == first


# --------------------------------------------------------------- community


@pytest.mark.parametrize("kind", COMMUNITY_KINDS)
def test_lists_return_the_workspaces_records_as_summaries(
    mock_omerlo, headers, tenant, workspace_id, kind
):
    items = fetch_all(mock_omerlo, list_path(workspace_id, kind), headers)

    assert {i["id"] for i in items} == {r["id"] for r in in_workspace(tenant, kind, workspace_id)}
    assert len({i["id"] for i in items}) == len(items)
    for item in items:
        SUMMARY_MODELS[kind].model_validate(item)


def test_records_in_other_workspaces_are_not_listed(mock_omerlo, headers, tenant):
    first, second = (w["id"] for w in tenant.resources["workspaces"])

    in_first = {o["id"] for o in fetch_all(mock_omerlo, list_path(first, "organizations"), headers)}
    in_second = {
        o["id"] for o in fetch_all(mock_omerlo, list_path(second, "organizations"), headers)
    }

    assert in_first
    assert in_second
    assert not in_first & in_second


@pytest.mark.parametrize("sort_by", SORT_VALUES)
def test_sort_by_orders_every_page(mock_omerlo, headers, orgs, sort_by):
    items = fetch_all(mock_omerlo, orgs, headers, sort_by=sort_by)

    field, direction = sort_by.rsplit("-", 1)
    keys = [(i[field], i["id"]) for i in items]
    assert keys == sorted(keys, reverse=direction == "desc")


def test_profile_type_filter(mock_omerlo, headers, tenant, workspace_id, orgs):
    wanted = in_workspace(tenant, "organizations", workspace_id)[0]["profile"]["profile_type_id"]

    items = fetch_all(mock_omerlo, orgs, headers, **{"profile_type_ids[]": wanted})

    assert items
    assert all(i["profile"]["profile_type_id"] == wanted for i in items)


@pytest.mark.parametrize("kind", COMMUNITY_KINDS)
def test_detail_returns_the_full_record(mock_omerlo, headers, tenant, kind):
    record = tenant.resources[kind][0]

    response = mock_omerlo.get(f"{COMMUNITY}/{kind}/{record['id']}", headers=headers)

    assert response.json() == {"data": record}
    MODELS[kind].model_validate(response.json()["data"])


def test_metadata_is_served_apart_from_the_record(mock_omerlo, headers, tenant):
    with_metadata = next(iter(tenant.metadata))
    without = next(
        o["id"] for o in tenant.resources["organizations"] if o["id"] not in tenant.metadata
    )

    def metadata(record_id):
        return mock_omerlo.get(f"{COMMUNITY}/organizations/{record_id}/metadata", headers=headers)

    assert metadata(with_metadata).json() == {"data": tenant.metadata[with_metadata]}
    assert metadata(without).json() == {"data": []}


def test_event_sessions(mock_omerlo, headers, tenant):
    event = tenant.resources["events"][0]

    response = mock_omerlo.get(f"{COMMUNITY}/events/{event['id']}/sessions", headers=headers)

    sessions = response.json()["data"]
    assert sessions
    assert sessions == [
        s for s in tenant.resources["event_sessions"] if s["event_id"] == event["id"]
    ]


def test_unknown_id_gets_404_and_malformed_id_gets_400(mock_omerlo, headers):
    unknown = f"{COMMUNITY}/organizations/00000000-0000-4000-8000-000000000000"
    malformed = f"{COMMUNITY}/organizations/not-a-uuid"

    assert mock_omerlo.get(unknown, headers=headers).json() == {"error": "entity not found"}
    assert mock_omerlo.get(unknown, headers=headers).status_code == 404
    assert mock_omerlo.get(malformed, headers=headers).json() == {"error": "Invalid uuid sent"}


# -------------------------------------------------------------- pagination


def test_response_has_data_and_meta(mock_omerlo, headers, orgs):
    body = mock_omerlo.get(orgs, headers=headers, params={"limit": 5}).json()

    assert set(body) == {"data", "meta"}
    assert len(body["data"]) == 5
    assert body["meta"]["base"] == orgs
    assert body["meta"]["next"]
    assert body["meta"]["previous"] is None


def test_before_returns_the_previous_page(mock_omerlo, headers, orgs):
    first = mock_omerlo.get(orgs, headers=headers, params={"limit": 5}).json()
    second = mock_omerlo.get(
        orgs, headers=headers, params={"limit": 5, "after": first["meta"]["next"]}
    ).json()

    back = mock_omerlo.get(
        orgs, headers=headers, params={"limit": 5, "before": second["meta"]["previous"]}
    ).json()

    assert back["data"] == first["data"]


def test_last_page_has_no_next(mock_omerlo, headers, tenant, workspace_id, orgs):
    total = len(in_workspace(tenant, "organizations", workspace_id))

    body = mock_omerlo.get(orgs, headers=headers, params={"limit": MAX_LIMIT}).json()

    assert len(body["data"]) == total
    assert body["meta"]["next"] is None


@pytest.mark.parametrize(
    "params",
    [
        {"after": "not-a-cursor"},
        {"after": encode_cursor("name-asc", "unknown-id")},
        {"after": encode_cursor("updated_at-desc", "x")},
        {"after": encode_cursor("inserted_at-asc", "x"), "before": "y"},
        {"limit": 0},
        {"limit": MAX_LIMIT + 1},
        {"sort_by": "colour-asc"},
    ],
)
def test_bad_parameters_get_400_with_an_error_body(mock_omerlo, headers, orgs, params):
    response = mock_omerlo.get(orgs, headers=headers, params=params)

    assert response.status_code == 400
    assert response.json()["error"]


def test_ground_truth_is_not_served(mock_omerlo, headers):
    for path in ("/api/ground_truth", "/ground_truth.dev_only.json"):
        assert mock_omerlo.get(path, headers=headers).status_code == 404


# --------------------------------------------------------------------- CLI


def test_cli_serves_fixture_files(tmp_path):
    write_fixtures(OmerloFixtureGenerator(5, SMALL).generate(), tmp_path, 5)

    app, args = build_app(["--fixtures", str(tmp_path), "--port", "9000"])

    assert args.port == 9000
    assert app.state.api_keys == {
        "mock-demo-capitale": "demo-capitale",
        "mock-demo-estrie": "demo-estrie",
    }


def test_cli_rejects_both_seed_and_fixtures(tmp_path):
    with pytest.raises(SystemExit):
        build_app(["--seed", "1", "--fixtures", str(tmp_path)])
