from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.core.tenancy import SYSTEM_KEY, TenantSession

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
    """An app session whose work is rolled back after the test.

    It starts with system access so tests can set up several tenants; code under test
    binds it to a tenant with bound_to_tenant(), as the API and the sync do.
    """
    connection = migrated_database.connect()
    transaction = connection.begin()
    session = TenantSession(
        bind=connection, join_transaction_mode="create_savepoint", info={SYSTEM_KEY: True}
    )
    yield session
    session.close()
    transaction.rollback()
    connection.close()
