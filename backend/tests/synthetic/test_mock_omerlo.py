import pytest

from synthetic.mock_omerlo import LIST_PATHS, MAX_LIMIT, TOKEN_PATH, encode_cursor
from tests.synthetic.conftest import SETTINGS

ORGS = LIST_PATHS["organizations"]


def fetch_all(client, path, headers, limit=7):
    items, params = [], {"limit": limit}
    while True:
        body = client.get(path, headers=headers, params=params).json()
        items += body["data"]
        if not body["meta"]["next"]:
            return items
        params = {"limit": limit, "after": body["meta"]["next"]}


# ------------------------------------------------------------------ tokens


def test_token_endpoint_issues_bearer_tokens(mock_omerlo):
    response = mock_omerlo.post(
        TOKEN_PATH,
        data={
            "grant_type": "client_credentials",
            "client_id": SETTINGS.client_id,
            "client_secret": SETTINGS.client_secret,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == SETTINGS.token_ttl_seconds
    assert body["access_token"]


def test_wrong_credentials_are_refused(mock_omerlo):
    response = mock_omerlo.post(
        TOKEN_PATH,
        data={"grant_type": "client_credentials", "client_id": "x", "client_secret": "y"},
    )

    assert response.status_code == 401
    assert response.json() == {"error": "invalid_client"}


def test_other_grant_types_are_unsupported(mock_omerlo):
    response = mock_omerlo.post(TOKEN_PATH, data={"grant_type": "refresh_token"})

    assert response.status_code == 400
    assert response.json() == {"error": "unsupported_grant_type"}


# ------------------------------------------------------------------ access


def test_requests_without_a_valid_token_get_401(mock_omerlo, headers):
    no_token = {k: v for k, v in headers.items() if k != "Authorization"}
    bad_token = {**headers, "Authorization": "Bearer nope"}

    assert mock_omerlo.get(ORGS, headers=no_token).status_code == 401
    assert mock_omerlo.get(ORGS, headers=bad_token).status_code == 401


def test_expired_tokens_get_401(mock_omerlo, headers, clock):
    assert mock_omerlo.get(ORGS, headers=headers).status_code == 200

    clock.now += SETTINGS.token_ttl_seconds

    assert mock_omerlo.get(ORGS, headers=headers).status_code == 401


def test_media_id_header_is_required_and_must_exist(mock_omerlo, headers):
    missing = {k: v for k, v in headers.items() if k != "x-omerlo-media-id"}

    assert mock_omerlo.get(ORGS, headers=missing).status_code == 400
    unknown = {**headers, "x-omerlo-media-id": "nobody"}
    assert mock_omerlo.get(ORGS, headers=unknown).status_code == 404


def test_data_is_scoped_to_the_media_id(mock_omerlo, headers, mock_tenants):
    first, second = (t.tenant.media_id for t in mock_tenants)

    ids_first = {o["id"] for o in fetch_all(mock_omerlo, ORGS, headers)}
    other = {**headers, "x-omerlo-media-id": second}
    ids_second = {o["id"] for o in fetch_all(mock_omerlo, ORGS, other)}

    assert ids_first == {o["id"] for o in mock_tenants[0].resources["organizations"]}
    assert ids_second == {o["id"] for o in mock_tenants[1].resources["organizations"]}
    assert not ids_first & ids_second
    assert first != second


# -------------------------------------------------------------- pagination


@pytest.mark.parametrize("kind", list(LIST_PATHS))
def test_following_next_returns_every_record_once_in_updated_at_order(
    mock_omerlo, headers, mock_tenants, kind
):
    items = fetch_all(mock_omerlo, LIST_PATHS[kind], headers)

    assert len(items) == len(mock_tenants[0].resources[kind])
    assert len({i["id"] for i in items}) == len(items)
    keys = [(i.get("updated_at") or "", i["id"]) for i in items]
    assert keys == sorted(keys)


def test_response_has_data_assocs_and_meta(mock_omerlo, headers):
    body = mock_omerlo.get(ORGS, headers=headers, params={"limit": 5}).json()

    assert set(body) == {"data", "assocs", "meta"}
    assert len(body["data"]) == 5
    assert body["meta"]["base"] == ORGS
    assert body["meta"]["next"]
    assert body["meta"]["previous"] is None


def test_before_returns_the_previous_page(mock_omerlo, headers):
    first = mock_omerlo.get(ORGS, headers=headers, params={"limit": 5}).json()
    second = mock_omerlo.get(
        ORGS, headers=headers, params={"limit": 5, "after": first["meta"]["next"]}
    ).json()

    back = mock_omerlo.get(
        ORGS, headers=headers, params={"limit": 5, "before": second["meta"]["previous"]}
    ).json()

    assert back["data"] == first["data"]


def test_last_page_has_no_next(mock_omerlo, headers, mock_tenants):
    total = len(mock_tenants[0].resources["organizations"])

    body = mock_omerlo.get(ORGS, headers=headers, params={"limit": MAX_LIMIT}).json()

    assert len(body["data"]) == total
    assert body["meta"]["next"] is None


def test_cursor_past_the_end_returns_an_empty_page(mock_omerlo, headers):
    body = mock_omerlo.get(
        ORGS, headers=headers, params={"after": encode_cursor(("9999", "z"))}
    ).json()

    assert body["data"] == []
    assert body["meta"]["next"] is None


@pytest.mark.parametrize(
    "params",
    [
        {"after": "not-a-cursor"},
        {"after": encode_cursor(("a", "b")), "before": encode_cursor(("a", "b"))},
    ],
)
def test_bad_cursors_get_400(mock_omerlo, headers, params):
    assert mock_omerlo.get(ORGS, headers=headers, params=params).status_code == 400


@pytest.mark.parametrize("limit", [0, MAX_LIMIT + 1])
def test_limit_out_of_range_is_rejected(mock_omerlo, headers, limit):
    assert mock_omerlo.get(ORGS, headers=headers, params={"limit": limit}).status_code == 422


def test_content_list_returns_summaries_with_category_assocs(mock_omerlo, headers):
    body = mock_omerlo.get(LIST_PATHS["contents"], headers=headers, params={"limit": 10}).json()

    assert all("blocks" not in c for c in body["data"])
    linked = {cid for c in body["data"] for cid in c["category_ids"]}
    assert {c["id"] for c in body["assocs"]["categories"]} == linked
