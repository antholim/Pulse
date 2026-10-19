import pytest
from fastapi.testclient import TestClient

from synthetic.fixture_loader import generate_fixtures
from synthetic.mock_omerlo import TOKEN_PATH, MockSettings, create_app
from synthetic.omerlo_fixtures import Sizes

SMALL = Sizes(organizations=30, people=40, contents=60, events=6, projects=4, authors=5)
SETTINGS = MockSettings(client_id="test-client", client_secret="test-secret", token_ttl_seconds=600)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture(scope="session")
def mock_tenants():
    return generate_fixtures(seed=11, sizes=SMALL)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def mock_omerlo(mock_tenants, clock):
    """A TestClient for the mock Omerlo server over small synthetic fixtures."""
    with TestClient(create_app(mock_tenants, SETTINGS, clock), base_url="http://mock-omerlo") as c:
        yield c


@pytest.fixture
def token(mock_omerlo):
    response = mock_omerlo.post(
        TOKEN_PATH,
        data={
            "grant_type": "client_credentials",
            "client_id": SETTINGS.client_id,
            "client_secret": SETTINGS.client_secret,
        },
    )
    return response.json()["access_token"]


@pytest.fixture
def headers(token, mock_tenants):
    return {
        "Authorization": f"Bearer {token}",
        "x-omerlo-media-id": mock_tenants[0].tenant.media_id,
    }
