from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture
def alembic_config(test_database) -> Config:
    """Alembic pointed at the test database (test_database sets DATABASE_URL)."""
    config = Config(str(ALEMBIC_INI))
    # Keep pytest's logging setup instead of the one in alembic.ini.
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture
def migrated_database(test_database, alembic_config):
    """The test database migrated to the latest schema, emptied again afterwards."""
    # Start from empty even if an interrupted run left tables behind.
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    yield test_database
    command.downgrade(alembic_config, "base")


@pytest.fixture
def session(migrated_database):
    """A session whose work is rolled back after the test."""
    connection = migrated_database.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()
