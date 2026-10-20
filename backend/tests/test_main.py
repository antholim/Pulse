from fastapi.testclient import TestClient

from app.core.request_context import REQUEST_ID_HEADER
from app.core.security import cors_origins
from app.main import app


def test_startup_and_shutdown_are_logged(log_output):
    with TestClient(app):
        pass

    app_entries = [entry for entry in log_output() if entry["module"] == "app.main"]
    assert [entry["event"] for entry in app_entries] == ["app_startup", "app_shutdown"]
    assert app_entries[0]["version"] == app.version


def test_api_responses_carry_a_request_id():
    response = TestClient(app).get("/api/health")

    assert len(response.headers[REQUEST_ID_HEADER]) == 32


def test_cors_preflight_responses_carry_a_request_id():
    response = TestClient(app).options(
        "/api/health",
        headers={"Origin": cors_origins()[0], "Access-Control-Request-Method": "GET"},
    )

    assert REQUEST_ID_HEADER in response.headers
