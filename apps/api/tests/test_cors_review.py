"""Regression coverage for the browser approval preflight boundary."""

from fastapi.testclient import TestClient

from app.main import app


def test_local_ui_can_preflight_review_token_header():
    client = TestClient(app)
    response = client.options(
        "/v1/workflows/00000000-0000-0000-0000-000000000001/decision",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-review-token",
        },
    )
    assert response.status_code == 200
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "x-review-token" in allowed
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_untrusted_origin_is_not_granted_review_token_access():
    client = TestClient(app)
    response = client.options(
        "/v1/workflows/00000000-0000-0000-0000-000000000001/decision",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-review-token",
        },
    )
    assert response.headers.get("access-control-allow-origin") is None
