from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import __version__
from app.core.config import Settings
from app.main import create_app


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app_name"] == "Kanoon AI Test"
    assert body["environment"] == "test"
    assert body["version"] == __version__
    assert "timestamp" in body


def test_response_carries_generated_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    request_id = response.headers.get("X-Request-ID")
    assert request_id is not None
    assert len(request_id) == 32


def test_valid_client_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "trace-123"})

    assert response.headers["X-Request-ID"] == "trace-123"


def test_unsafe_client_request_id_is_replaced(client: TestClient) -> None:
    unsafe_id = "bad id; with spaces"
    response = client.get("/api/v1/health", headers={"X-Request-ID": unsafe_id})

    assert response.headers["X-Request-ID"] != unsafe_id
    assert len(response.headers["X-Request-ID"]) == 32


def test_cors_preflight_allows_configured_origin(client: TestClient) -> None:
    response = client.options(
        "/api/v1/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_rejects_unknown_origin(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})

    assert "access-control-allow-origin" not in response.headers


def test_unhandled_error_returns_problem_json_without_details(app: FastAPI) -> None:
    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    with TestClient(app) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert "secret internal detail" not in response.text


def test_docs_hidden_in_production(settings: Settings) -> None:
    prod_app = create_app(settings.model_copy(update={"environment": "production"}))

    with TestClient(prod_app) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/api/v1/health").status_code == 200
