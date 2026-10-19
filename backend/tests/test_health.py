from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

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
    assert response.json() == {"detail": "Database unavailable"}
