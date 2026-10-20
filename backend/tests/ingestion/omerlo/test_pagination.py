import httpx
import pytest
import respx

from app.ingestion.omerlo.client import OmerloAPIError
from app.ingestion.omerlo.pagination import paginate

BASE_URL = "https://omerlo.test/api"
PATH = "/core/v2/categories"
URL = BASE_URL + PATH


def page(items, next_page=None):
    return httpx.Response(
        200, json={"data": items, "meta": {"base": PATH, "next": next_page, "previous": None}}
    )


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL) as c:
        yield c


@respx.mock
def test_follows_next_cursor_until_the_last_page(client):
    route = respx.get(URL).mock(
        side_effect=[page([{"id": "1"}, {"id": "2"}], "c2"), page([{"id": "3"}], None)]
    )

    items = list(paginate(client, PATH, page_size=2))

    assert [i["id"] for i in items] == ["1", "2", "3"]
    first, second = (dict(c.request.url.params) for c in route.calls)
    assert first == {"limit": "2"}
    assert second == {"limit": "2", "after": "c2"}


@respx.mock
def test_limit_is_left_out_when_no_page_size_is_given(client):
    route = respx.get(URL).mock(return_value=page([{"id": "1"}]))

    list(paginate(client, PATH, params={"sort_by": "updated_at-desc"}))

    assert dict(route.calls.last.request.url.params) == {"sort_by": "updated_at-desc"}


@respx.mock
def test_extra_params_are_kept_on_every_page(client):
    route = respx.get(URL).mock(side_effect=[page([{"id": "1"}], "c2"), page([], None)])

    list(paginate(client, PATH, params={"sort_by": "updated_at-desc"}))

    assert all(c.request.url.params["sort_by"] == "updated_at-desc" for c in route.calls)


@respx.mock
def test_absolute_next_url_on_the_same_host_is_followed_as_is(client):
    next_url = f"{URL}?page=2"
    respx.get(URL, params={"page": "2"}).mock(return_value=page([{"id": "2"}]))
    respx.get(URL).mock(return_value=page([{"id": "1"}], next_url))

    assert [i["id"] for i in paginate(client, PATH)] == ["1", "2"]


@respx.mock
def test_next_url_on_another_host_is_refused(client):
    respx.get(URL).mock(return_value=page([{"id": "1"}], "https://elsewhere.test/steal"))

    with pytest.raises(OmerloAPIError, match="another host"):
        list(paginate(client, PATH))


@respx.mock
def test_response_without_meta_is_a_single_page(client):
    respx.get(URL).mock(return_value=httpx.Response(200, json={"data": [{"id": "1"}]}))

    assert len(list(paginate(client, PATH))) == 1


@respx.mock
def test_stops_on_empty_page_even_with_a_cursor(client):
    route = respx.get(URL).mock(side_effect=[page([{"id": "1"}], "c2"), page([], "c3")])

    assert len(list(paginate(client, PATH))) == 1
    assert route.call_count == 2


@respx.mock
def test_repeated_cursor_raises_instead_of_looping(client):
    respx.get(URL).mock(side_effect=[page([{"id": "1"}], "c2"), page([{"id": "2"}], "c2")])

    with pytest.raises(OmerloAPIError, match="returned twice"):
        list(paginate(client, PATH))


@respx.mock
def test_response_without_a_data_list_raises(client):
    respx.get(URL).mock(return_value=httpx.Response(200, json={"meta": {}}))

    with pytest.raises(OmerloAPIError, match="no data list"):
        list(paginate(client, PATH))
