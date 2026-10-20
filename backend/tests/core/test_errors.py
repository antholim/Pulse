from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import (
    INTERNAL_ERROR_MESSAGE,
    ConnectorError,
    DataValidationError,
    NotFoundError,
    PulseError,
    register_exception_handlers,
)
from app.core.request_context import REQUEST_ID_HEADER, RequestContextMiddleware
from app.main import app


def make_client() -> TestClient:
    small_app = FastAPI()
    register_exception_handlers(small_app)
    small_app.add_middleware(RequestContextMiddleware)

    @small_app.get("/organizations/{org_id}")
    def get_organization(org_id: int):
        raise NotFoundError(f"Organization {org_id} not found", details={"organization_id": org_id})

    @small_app.post("/imports")
    def run_import():
        raise DataValidationError("Row 3 is missing a name", details={"row": 3})

    @small_app.post("/syncs")
    def run_sync():
        raise ConnectorError("Omerlo did not answer", source="omerlo")

    @small_app.get("/pulse-error")
    def plain_pulse_error():
        raise PulseError("Something PULSE knows about failed")

    @small_app.get("/crash")
    def crash():
        raise RuntimeError("database exploded while emailing marie@exemple.qc.ca")

    # Unhandled errors are re-raised by Starlette after the 500 response is sent.
    return TestClient(small_app, raise_server_exceptions=False)


def test_not_found_error_uses_the_standard_body():
    response = make_client().get("/organizations/7")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "Organization 7 not found",
            "details": {"organization_id": 7},
            "request_id": response.headers[REQUEST_ID_HEADER],
        }
    }


def test_data_validation_error_is_a_422():
    response = make_client().post("/imports")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"] == {"row": 3}


def test_connector_error_is_a_502_naming_the_source():
    response = make_client().post("/syncs")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "connector_error"
    assert response.json()["error"]["details"] == {"source": "omerlo"}


def test_base_pulse_error_is_an_internal_error():
    response = make_client().get("/pulse-error")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert response.json()["error"]["message"] == "Something PULSE knows about failed"


def test_unexpected_errors_hide_the_cause_from_the_client():
    response = make_client().get("/crash")

    assert response.status_code == 500
    body = response.json()["error"]
    assert body["code"] == "internal_error"
    assert body["message"] == INTERNAL_ERROR_MESSAGE
    assert body["details"] is None
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]
    assert "exploded" not in response.text
    assert "Traceback" not in response.text


def test_unexpected_errors_are_logged_with_trace_and_request_id(log_output):
    response = make_client().get("/crash")

    entry = next(e for e in log_output() if e["event"] == "unhandled_error")
    assert entry["level"] == "error"
    assert entry["request_id"] == response.headers[REQUEST_ID_HEADER]
    assert "RuntimeError: database exploded while emailing [EMAIL]" in entry["exception"]


def test_server_side_pulse_errors_log_at_error_and_client_errors_at_warning(log_output):
    client = make_client()
    client.post("/syncs")
    client.get("/organizations/7")

    levels = {e["code"]: e["level"] for e in log_output() if e["event"] == "pulse_error"}
    assert levels == {"connector_error": "error", "not_found": "warning"}


def test_request_validation_errors_use_the_standard_body_without_the_input():
    response = make_client().get("/organizations/not-a-number")

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert body["message"] == "The request is invalid."
    [error] = body["details"]["errors"]
    assert error == {
        "location": ["path", "org_id"],
        "message": "Input should be a valid integer, unable to parse string as an integer",
        "type": "int_parsing",
    }


def test_unknown_routes_use_the_standard_body():
    response = make_client().get("/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["message"] == "Not Found"


def test_the_real_app_uses_the_standard_error_body():
    response = TestClient(app).get("/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
