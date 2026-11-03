import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from app.core.errors import register_exception_handlers
from app.core.security import (
    SECURITY_HEADERS,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
    cors_origins,
    max_request_bytes,
)
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


def size_limited_client(max_bytes: int) -> TestClient:
    small_app = FastAPI()
    register_exception_handlers(small_app)
    small_app.add_middleware(RequestSizeLimitMiddleware, max_bytes=max_bytes)

    @small_app.post("/echo")
    async def echo(request: Request):
        return {"size": len(await request.body())}

    return TestClient(small_app)


def test_body_within_the_limit_is_accepted():
    # Arrange
    limited = size_limited_client(max_bytes=10)

    # Act
    response = limited.post("/echo", content=b"x" * 10)

    # Assert
    assert response.status_code == 200
    assert response.json() == {"size": 10}


def test_declared_body_over_the_limit_is_rejected():
    # Arrange
    limited = size_limited_client(max_bytes=10)

    # Act
    response = limited.post("/echo", content=b"x" * 11)

    # Assert
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_streamed_body_over_the_limit_is_rejected():
    # Arrange
    limited = size_limited_client(max_bytes=10)
    chunks = iter([b"x" * 6, b"x" * 6])

    # Act
    response = limited.post("/echo", content=chunks)

    # Assert
    assert "content-length" not in response.request.headers
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_oversized_request_still_gets_the_security_headers():
    # Arrange
    too_large = str(max_request_bytes() + 1)

    # Act
    response = client.post("/api/health", headers={"Content-Length": too_large}, content=b"")

    # Assert
    assert response.status_code == 413
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_max_request_bytes_defaults_to_ten_megabytes(monkeypatch):
    # Arrange
    monkeypatch.delenv("MAX_REQUEST_BYTES", raising=False)

    # Act / Assert
    assert max_request_bytes() == 10 * 1024 * 1024


def test_max_request_bytes_from_environment(monkeypatch):
    # Arrange
    monkeypatch.setenv("MAX_REQUEST_BYTES", "2048")

    # Act / Assert
    assert max_request_bytes() == 2048


def test_max_request_bytes_rejects_zero(monkeypatch):
    # Arrange
    monkeypatch.setenv("MAX_REQUEST_BYTES", "0")

    # Act / Assert
    with pytest.raises(ValueError, match="positive"):
        max_request_bytes()
