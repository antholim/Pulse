import os
from functools import cache
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# Load the .env file from the PULSE root directory
ROOT_DIR = Path(__file__).resolve().parents[3]
load_dotenv(ROOT_DIR / ".env")


# Created on first use, so importing the app (for example in tests) does not
# require DATABASE_URL.
@cache
def get_engine() -> Engine:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set; see .env.example")
    return create_engine(database_url, pool_pre_ping=True)


@cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)


def get_db():
    with get_session_factory()() as db:
        yield db


def check_database():
    with get_engine().connect() as connection:
        return connection.execute(text("SELECT 1")).scalar_one()
