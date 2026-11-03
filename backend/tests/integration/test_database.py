# AI contribution: 50% or more AI-generated
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.database import check_database, get_db
from app.core.tenancy import system_access
from app.main import app

pytestmark = pytest.mark.integration


def test_check_database_reaches_postgres(test_database):
    assert check_database() == 1


def test_session_runs_queries(test_database):
    session = next(get_db())
    try:
        with system_access(session):
            version = session.execute(text("SELECT version()")).scalar_one()
        assert version.startswith("PostgreSQL")
    finally:
        session.close()


def test_database_health_endpoint(test_database):
    response = TestClient(app).get("/health/db")

    assert response.status_code == 200
    assert response.json() == {"database": "connected"}
