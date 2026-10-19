import pytest

from app.core import database


@pytest.fixture(autouse=True)
def fresh_engine():
    database.get_engine.cache_clear()
    database.get_session_factory.cache_clear()
    yield
    database.get_engine.cache_clear()
    database.get_session_factory.cache_clear()


def test_missing_database_url_raises_a_clear_error(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
        database.get_engine()


def test_engine_is_created_once(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/pulse")

    assert database.get_engine() is database.get_engine()
    assert database.get_session_factory().kw["bind"] is database.get_engine()
