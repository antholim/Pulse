from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.core import database
from app.core.database import DatabaseNotConfiguredError
from app.main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "pulse-backend",
    }


def test_database_health_when_connected(mocker):
    check = mocker.patch("app.main.check_database", return_value=1)

    response = client.get("/health/db")

    assert response.status_code == 200
    assert response.json() == {"database": "connected"}
    check.assert_called_once()


def test_database_health_when_unavailable(mocker):
    mocker.patch(
        "app.main.check_database",
        side_effect=OperationalError("SELECT 1", {}, Exception("connection refused")),
    )

    response = client.get("/health/db")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert response.json()["error"]["message"] == "Database unavailable"


def test_database_outage_is_logged_with_its_cause(mocker, log_output):
    mocker.patch(
        "app.main.check_database",
        side_effect=OperationalError("SELECT 1", {}, Exception("connection refused")),
    )

    client.get("/health/db")

    [entry] = [e for e in log_output() if e["event"] == "http_error"]
    assert entry["level"] == "error"
    assert entry["status_code"] == 503
    assert "OperationalError" in entry["exception"]


def test_database_health_when_not_configured(mocker):
    mocker.patch(
        "app.main.check_database",
        side_effect=DatabaseNotConfiguredError("DATABASE_URL is not set"),
    )

    response = client.get("/health/db")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert response.json()["error"]["message"] == "Database unavailable"


def test_database_health_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    database.get_engine.cache_clear()
    try:
        response = client.get("/health/db")
    finally:
        database.get_engine.cache_clear()

    assert response.status_code == 503
