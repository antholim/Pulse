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


@pytest.mark.parametrize(
    "url",
    [
        "postgres://user:pass@pulse-db.flycast:5432/pulse",
        "postgresql://user:pass@pulse-db.flycast:5432/pulse",
        "postgresql+psycopg://user:pass@pulse-db.flycast:5432/pulse",
    ],
)
def test_plain_postgres_urls_use_the_psycopg_driver(url):
    # Act / Assert
    assert (
        database.sqlalchemy_url(url) == "postgresql+psycopg://user:pass@pulse-db.flycast:5432/pulse"
    )


def test_engine_accepts_the_postgres_scheme(monkeypatch):
    # Arrange
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@localhost:5432/pulse")

    # Act
    engine = database.get_engine()

    # Assert
    assert engine.url.drivername == "postgresql+psycopg"
