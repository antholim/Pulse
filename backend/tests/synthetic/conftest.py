import pytest
from fastapi.testclient import TestClient

from synthetic.fixture_loader import generate_fixtures
from synthetic.mock_omerlo import api_key_for, create_app
from synthetic.omerlo_fixtures import Sizes

SMALL = Sizes(organizations=30, people=40, events=6, projects=4, journalists=5)


@pytest.fixture(scope="session")
def mock_tenants():
    return generate_fixtures(seed=11, sizes=SMALL)


@pytest.fixture
def mock_omerlo(mock_tenants):
    """A TestClient for the mock Omerlo server over small synthetic fixtures."""
    with TestClient(create_app(mock_tenants), base_url="http://mock-omerlo") as c:
        yield c


@pytest.fixture
def headers(mock_tenants):
    return {"x-api-key": api_key_for(mock_tenants[0].tenant.slug)}
