import os

import pytest

from app.core import database


@pytest.fixture
def test_database(monkeypatch):
    """Point the app at the real test database, or skip when none is configured.

    Start one with `docker compose --profile test up -d test-db` and set
    TEST_DATABASE_URL (see .env.example). CI provides it as a service.
    """
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    monkeypatch.setenv("DATABASE_URL", url)
    database.get_engine.cache_clear()
    database.get_session_factory.cache_clear()
    yield database.get_engine()
    database.get_engine().dispose()
    database.get_engine.cache_clear()
    database.get_session_factory.cache_clear()
