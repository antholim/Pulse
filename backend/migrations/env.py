from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection

from app.core.database import get_engine
from app.models import Base

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Tests pass their own connection; otherwise connect through DATABASE_URL.
    connection = config.attributes.get("connection")
    if connection is not None:
        run_migrations(connection)
        return
    with get_engine().connect() as connection:
        run_migrations(connection)


if context.is_offline_mode():
    raise RuntimeError("Offline (--sql) migrations are not supported; run against a database")

run_migrations_online()
