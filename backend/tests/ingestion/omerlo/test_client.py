import httpx
import pytest
import respx

from app.ingestion.omerlo.client import (
    API_KEY_HEADER,
    OmerloAPIError,
    OmerloAuthError,
    OmerloNotFoundError,
    create_omerlo_client,
    get_json,
)
from app.ingestion.omerlo.settings import OmerloSettings

BASE_URL = "https://omerlo.test/api"
SECRET = "s3cret-key"


@pytest.fixture
def settings():
    return OmerloSettings(base_url=BASE_URL, api_key=SECRET, timeout_seconds=5)


@pytest.fixture
def client(settings):
    with create_omerlo_client(settings) as c:
        yield c


def test_settings_are_read_from_omerlo_variables(monkeypatch):
    monkeypatch.setenv("OMERLO_BASE_URL", BASE_URL)
    monkeypatch.setenv("OMERLO_API_KEY", SECRET)

    settings = OmerloSettings()

    assert settings.api_key.get_secret_value() == SECRET
    assert SECRET not in repr(settings)


@respx.mock
def test_client_sends_the_api_key_header_under_the_api_prefix(client):
    route = respx.get(f"{BASE_URL}/composer/v2/workspaces").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    assert get_json(client, "/composer/v2/workspaces") == {"data": []}
    request = route.calls.last.request
    assert request.headers[API_KEY_HEADER] == SECRET
    assert "api_key" not in request.url.params


def test_client_uses_the_configured_timeout(client):
    assert client.timeout.read == 5


@respx.mock
@pytest.mark.parametrize("status", [401, 403])
def test_rejected_key_or_missing_role_raises_an_auth_error(client, status):
    respx.get(f"{BASE_URL}/x").mock(
        return_value=httpx.Response(status, json={"error": "Unauthorized access"})
    )

    with pytest.raises(OmerloAuthError, match=f"HTTP {status}") as excinfo:
        get_json(client, "/x")
    assert SECRET not in str(excinfo.value)


@respx.mock
def test_missing_record_raises_not_found_with_the_api_message(client):
    respx.get(f"{BASE_URL}/x").mock(
        return_value=httpx.Response(404, json={"error": "entity not found"})
    )

    with pytest.raises(OmerloNotFoundError, match="entity not found"):
        get_json(client, "/x")


@respx.mock
def test_not_found_without_an_error_body_still_raises(client):
    respx.get(f"{BASE_URL}/x").mock(return_value=httpx.Response(404, text="gone"))

    with pytest.raises(OmerloNotFoundError, match="HTTP 404"):
        get_json(client, "/x")


@respx.mock
@pytest.mark.parametrize("status", [400, 500, 503])
def test_other_errors_are_raised_for_the_sync_run_to_handle(client, status):
    respx.get(f"{BASE_URL}/x").mock(return_value=httpx.Response(status, json={"error": "boom"}))

    with pytest.raises(httpx.HTTPStatusError):
        get_json(client, "/x")


@respx.mock
@pytest.mark.parametrize(
    "response",
    [httpx.Response(200, text="<html>oops</html>"), httpx.Response(200, json=["a", "list"])],
)
def test_malformed_response_raises(client, response):
    respx.get(f"{BASE_URL}/x").mock(return_value=response)

    with pytest.raises(OmerloAPIError):
        get_json(client, "/x")
