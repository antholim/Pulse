import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.request_context import (
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
    current_request_id,
)


def make_client() -> TestClient:
    small_app = FastAPI()
    small_app.add_middleware(RequestContextMiddleware)

    @small_app.get("/whoami")
    def whoami():
        return {"request_id": current_request_id()}

    return TestClient(small_app)


def test_each_response_gets_a_generated_request_id():
    client = make_client()

    first = client.get("/whoami")
    second = client.get("/whoami")

    assert first.headers[REQUEST_ID_HEADER] == first.json()["request_id"]
    assert len(first.headers[REQUEST_ID_HEADER]) == 32
    assert first.headers[REQUEST_ID_HEADER] != second.headers[REQUEST_ID_HEADER]


def test_a_valid_incoming_request_id_is_reused():
    response = make_client().get("/whoami", headers={REQUEST_ID_HEADER: "fly-abc.123_X"})

    assert response.headers[REQUEST_ID_HEADER] == "fly-abc.123_X"
    assert response.json()["request_id"] == "fly-abc.123_X"


@pytest.mark.parametrize("unsafe", ["has space", "x" * 129, "semi;colon"])
def test_an_unsafe_incoming_request_id_is_replaced(unsafe):
    response = make_client().get("/whoami", headers={REQUEST_ID_HEADER: unsafe})

    assert response.headers[REQUEST_ID_HEADER] != unsafe
    assert len(response.headers[REQUEST_ID_HEADER]) == 32


def test_every_request_is_logged_with_its_id_and_outcome(log_output):
    response = make_client().get("/whoami?api_key=should-not-appear")

    entries = log_output()
    entry = next(e for e in entries if e["event"] == "request_completed")
    assert entry["request_id"] == response.headers[REQUEST_ID_HEADER]
    assert entry["method"] == "GET"
    assert entry["path"] == "/whoami"
    assert entry["status_code"] == 200
    assert entry["duration_ms"] >= 0
    assert "should-not-appear" not in json.dumps(entries)
