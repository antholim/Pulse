import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from app.core.security import SECURITY_HEADERS, SecurityHeadersMiddleware, cors_origins
from app.main import app

client = TestClient(app)


def test_security_headers_on_every_response():
    response = client.get("/api/health")

    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value


def test_security_headers_on_error_responses():
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_startup_and_shutdown_pass_through_the_middleware():
    # Using the client as a context manager runs the lifespan scope through the middleware.
    with TestClient(app) as lifespan_client:
        assert lifespan_client.get("/api/health").status_code == 200


def test_route_can_override_a_security_header():
    small_app = FastAPI()
    small_app.add_middleware(SecurityHeadersMiddleware)

    @small_app.get("/embeddable")
    def embeddable(response: Response):
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        return {}

    response = TestClient(small_app).get("/embeddable")

    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert response.headers["Referrer-Policy"] == "no-referrer"


@pytest.mark.parametrize("method", ["GET", "QUERY"])
def test_cors_allows_the_frontend_origin(method):
    origin = cors_origins()[0]

    response = client.options(
        "/api/health",
        headers={"Origin": origin, "Access-Control-Request-Method": method},
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == origin
    assert method in response.headers["Access-Control-Allow-Methods"]


def test_cors_rejects_unlisted_methods():
    response = client.options(
        "/api/health",
        headers={"Origin": cors_origins()[0], "Access-Control-Request-Method": "TRACE"},
    )

    assert response.status_code == 400


def test_cors_rejects_other_origins():
    response = client.options(
        "/api/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 400
    assert "Access-Control-Allow-Origin" not in response.headers


def test_cors_origins_default_to_the_vite_dev_server(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    assert cors_origins() == ["http://localhost:5173"]


def test_cors_origins_from_environment(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", " https://pulse.example/ , http://localhost:5173 ,")

    assert cors_origins() == ["https://pulse.example", "http://localhost:5173"]


def test_cors_origins_reject_a_wildcard(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173,*")

    with pytest.raises(ValueError, match="explicit origins"):
        cors_origins()
