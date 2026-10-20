import io
import json
import os

import pytest
import structlog

from app.core import database
from app.core.logging import configure_logging


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


@pytest.fixture
def log_output():
    """Send logs to a buffer at DEBUG level; call the result to get the JSON lines."""
    stream = io.StringIO()
    configure_logging(level="DEBUG", stream=stream)
    yield lambda: [json.loads(line) for line in stream.getvalue().splitlines()]
    structlog.contextvars.clear_contextvars()
    configure_logging()
