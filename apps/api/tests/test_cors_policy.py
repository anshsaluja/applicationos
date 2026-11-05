"""Browser-origin policy regression tests; no database or external services required."""

from fastapi.testclient import TestClient

from app.main import app


def test_local_frontend_origin_is_allowed() -> None:
    with TestClient(app) as client:
        response = client.options(
            "/v1/documents",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_untrusted_browser_origin_is_denied() -> None:
    with TestClient(app) as client:
        response = client.options(
            "/v1/documents",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "POST",
            },
        )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_browser_cannot_preflight_authorization_header() -> None:
    with TestClient(app) as client:
        response = client.options(
            "/v1/documents",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization",
            },
        )
    assert response.status_code == 400
    assert "authorization" not in response.headers.get("access-control-allow-headers", "").lower()
