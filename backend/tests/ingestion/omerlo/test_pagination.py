import httpx
import pytest
import respx

from app.ingestion.omerlo.pagination import OmerloAPIError, paginate

BASE_URL = "https://omerlo.test"
PATH = "/api/media/v1/contents"
URL = BASE_URL + PATH


def page(items, next_cursor=None):
    return httpx.Response(
        200, json={"data": items, "assocs": {}, "meta": {"next": next_cursor, "previous": None}}
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
def test_extra_params_are_kept_on_every_page(client):
    route = respx.get(URL).mock(side_effect=[page([{"id": "1"}], "c2"), page([], None)])

    list(paginate(client, PATH, params={"locale": "fr"}))

    assert all(c.request.url.params["locale"] == "fr" for c in route.calls)


@respx.mock
def test_empty_first_page_yields_nothing(client):
    respx.get(URL).mock(return_value=page([], "ignored"))

    assert list(paginate(client, PATH)) == []


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
def test_http_error_is_raised(client):
    respx.get(URL).mock(return_value=httpx.Response(503))

    with pytest.raises(httpx.HTTPStatusError):
        list(paginate(client, PATH))


@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>oops</html>"),
        httpx.Response(200, json=["not", "an", "object"]),
        httpx.Response(200, json={"meta": {}}),
    ],
)
def test_malformed_response_raises(client, response):
    respx.get(URL).mock(return_value=response)

    with pytest.raises(OmerloAPIError):
        list(paginate(client, PATH))
