import logging
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from app.ingestion.omerlo.auth import (
    MEDIA_ID_HEADER,
    OmerloAuth,
    OmerloAuthError,
    create_omerlo_client,
)
from app.ingestion.omerlo.settings import OmerloSettings

BASE_URL = "https://omerlo.test"
TOKEN_URL = "https://auth.omerlo.test/oauth/token"
CONTENTS_URL = f"{BASE_URL}/api/media/v1/contents"
SECRET = "s3cret-value"


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def settings():
    return OmerloSettings(
        base_url=BASE_URL,
        token_url=TOKEN_URL,
        client_id="pulse-client",
        client_secret=SECRET,
        media_id="media-42",
        token_refresh_margin_seconds=60,
    )


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def client(settings, clock):
    with httpx.Client(base_url=BASE_URL, auth=OmerloAuth(settings, clock=clock)) as c:
        yield c


def token_response(access_token, expires_in=3600, refresh_token=None):
    payload = {"access_token": access_token, "token_type": "Bearer"}
    if expires_in is not None:
        payload["expires_in"] = expires_in
    if refresh_token:
        payload["refresh_token"] = refresh_token
    return httpx.Response(200, json=payload)


def form(request):
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


@respx.mock
def test_first_request_fetches_token_and_signs_request(client):
    token_route = respx.post(TOKEN_URL).mock(return_value=token_response("tok-1"))
    api_route = respx.get(CONTENTS_URL).mock(return_value=httpx.Response(200, json={"data": []}))

    response = client.get("/api/media/v1/contents")

    assert response.status_code == 200
    assert form(token_route.calls.last.request) == {
        "grant_type": "client_credentials",
        "client_id": "pulse-client",
        "client_secret": SECRET,
    }
    sent = api_route.calls.last.request
    assert sent.headers["Authorization"] == "Bearer tok-1"
    assert sent.headers[MEDIA_ID_HEADER] == "media-42"


@respx.mock
def test_token_is_cached_between_requests(client):
    token_route = respx.post(TOKEN_URL).mock(return_value=token_response("tok-1"))
    respx.get(CONTENTS_URL).mock(return_value=httpx.Response(200))

    client.get("/api/media/v1/contents")
    client.get("/api/media/v1/contents")

    assert token_route.call_count == 1


@respx.mock
def test_token_is_refreshed_before_expiry(client, clock):
    token_route = respx.post(TOKEN_URL).mock(
        side_effect=[token_response("tok-1", expires_in=600), token_response("tok-2")]
    )
    api_route = respx.get(CONTENTS_URL).mock(return_value=httpx.Response(200))

    client.get("/api/media/v1/contents")
    clock.now += 600 - 60 - 1  # still outside the refresh margin
    client.get("/api/media/v1/contents")
    assert token_route.call_count == 1

    clock.now += 1  # now inside the margin
    client.get("/api/media/v1/contents")

    assert token_route.call_count == 2
    assert api_route.calls.last.request.headers["Authorization"] == "Bearer tok-2"


@respx.mock
def test_short_lived_token_is_reused_until_half_its_lifetime(client, clock):
    # expires_in (30 s) is shorter than the 60 s margin, so the margin shrinks to 15 s.
    token_route = respx.post(TOKEN_URL).mock(
        side_effect=[token_response("tok-1", expires_in=30), token_response("tok-2")]
    )
    respx.get(CONTENTS_URL).mock(return_value=httpx.Response(200))

    client.get("/api/media/v1/contents")
    clock.now += 14
    client.get("/api/media/v1/contents")
    assert token_route.call_count == 1

    clock.now += 1
    client.get("/api/media/v1/contents")
    assert token_route.call_count == 2


@respx.mock
@pytest.mark.parametrize("expires_in", ["soon", [3600], {"s": 1}])
def test_invalid_expires_in_raises(client, expires_in):
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "tok-1", "expires_in": expires_in})
    )

    with pytest.raises(OmerloAuthError, match="invalid expires_in"):
        client.get("/api/media/v1/contents")


@respx.mock
def test_token_without_expiry_is_kept_until_rejected(client, clock):
    token_route = respx.post(TOKEN_URL).mock(return_value=token_response("tok-1", expires_in=None))
    respx.get(CONTENTS_URL).mock(return_value=httpx.Response(200))

    client.get("/api/media/v1/contents")
    clock.now += 10**9
    client.get("/api/media/v1/contents")

    assert token_route.call_count == 1


@respx.mock
def test_401_fetches_new_token_and_retries_once(client):
    token_route = respx.post(TOKEN_URL).mock(
        side_effect=[token_response("tok-1"), token_response("tok-2")]
    )
    api_route = respx.get(CONTENTS_URL).mock(
        side_effect=[httpx.Response(401), httpx.Response(200, json={"data": []})]
    )

    response = client.get("/api/media/v1/contents")

    assert response.status_code == 200
    assert token_route.call_count == 2
    assert [c.request.headers["Authorization"] for c in api_route.calls] == [
        "Bearer tok-1",
        "Bearer tok-2",
    ]


@respx.mock
def test_second_401_is_returned_without_looping(client):
    token_route = respx.post(TOKEN_URL).mock(
        side_effect=[token_response("tok-1"), token_response("tok-2")]
    )
    api_route = respx.get(CONTENTS_URL).mock(return_value=httpx.Response(401))

    response = client.get("/api/media/v1/contents")

    assert response.status_code == 401
    assert token_route.call_count == 2
    assert api_route.call_count == 2


@respx.mock
def test_invalid_credentials_raise_without_leaking_the_secret(client):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(401, json={"error": "invalid_client"}))
    api_route = respx.get(CONTENTS_URL).mock(return_value=httpx.Response(200))

    with pytest.raises(OmerloAuthError, match="HTTP 401") as exc_info:
        client.get("/api/media/v1/contents")

    assert SECRET not in str(exc_info.value)
    assert api_route.call_count == 0


@respx.mock
def test_token_response_without_access_token_raises(client):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"token_type": "Bearer"}))

    with pytest.raises(OmerloAuthError, match="no access_token"):
        client.get("/api/media/v1/contents")


@respx.mock
def test_refresh_token_is_used_when_provided(client, clock):
    token_route = respx.post(TOKEN_URL).mock(
        side_effect=[
            token_response("tok-1", expires_in=120, refresh_token="ref-1"),
            token_response("tok-2"),
        ]
    )
    respx.get(CONTENTS_URL).mock(return_value=httpx.Response(200))

    client.get("/api/media/v1/contents")
    clock.now += 120
    client.get("/api/media/v1/contents")

    refresh = form(token_route.calls.last.request)
    assert refresh["grant_type"] == "refresh_token"
    assert refresh["refresh_token"] == "ref-1"


@respx.mock
def test_rejected_refresh_token_falls_back_to_client_credentials(client, clock):
    token_route = respx.post(TOKEN_URL).mock(
        side_effect=[
            token_response("tok-1", expires_in=120, refresh_token="ref-1"),
            httpx.Response(400, json={"error": "invalid_grant"}),
            token_response("tok-2"),
        ]
    )
    api_route = respx.get(CONTENTS_URL).mock(return_value=httpx.Response(200))

    client.get("/api/media/v1/contents")
    clock.now += 120
    client.get("/api/media/v1/contents")

    grants = [form(c.request)["grant_type"] for c in token_route.calls]
    assert grants == ["client_credentials", "refresh_token", "client_credentials"]
    assert api_route.calls.last.request.headers["Authorization"] == "Bearer tok-2"


@respx.mock
def test_tokens_and_secret_are_never_logged(client, caplog):
    respx.post(TOKEN_URL).mock(return_value=token_response("tok-1", refresh_token="ref-1"))
    respx.get(CONTENTS_URL).mock(return_value=httpx.Response(200))

    with caplog.at_level(logging.DEBUG):
        client.get("/api/media/v1/contents")

    logged = caplog.text
    assert "Obtained a new Omerlo access token" in logged
    for value in ("tok-1", "ref-1", SECRET):
        assert value not in logged


@respx.mock
def test_create_omerlo_client_uses_settings(settings):
    respx.post(TOKEN_URL).mock(return_value=token_response("tok-1"))
    api_route = respx.get(CONTENTS_URL).mock(return_value=httpx.Response(200))

    with create_omerlo_client(settings) as c:
        c.get("/api/media/v1/contents")

    assert api_route.calls.last.request.headers[MEDIA_ID_HEADER] == "media-42"


def test_settings_load_from_environment(monkeypatch):
    monkeypatch.setenv("OMERLO_BASE_URL", BASE_URL)
    monkeypatch.setenv("OMERLO_TOKEN_URL", TOKEN_URL)
    monkeypatch.setenv("OMERLO_CLIENT_ID", "pulse-client")
    monkeypatch.setenv("OMERLO_CLIENT_SECRET", SECRET)
    monkeypatch.setenv("OMERLO_MEDIA_ID", "media-42")

    loaded = OmerloSettings()

    assert loaded.media_id == "media-42"
    assert loaded.client_secret.get_secret_value() == SECRET
    assert SECRET not in repr(loaded)
