"""Security regression tests for API response hardening and CORS boundaries."""

import pytest
from fastapi.testclient import TestClient

from app.main import app, parse_cors_origins


@pytest.mark.parametrize(
    "value",
    [
        "*",
        "https://*.example.com",
        "https://example.com/path",
        "https://example.com?next=1",
        "https://example.com#fragment",
        "https://user:password@example.com",
        "ftp://example.com",
        "https://example.com:99999",
        "https://example.com:0",
        "https://",
    ],
)
def test_cors_rejects_non_origin_values(value: str) -> None:
    with pytest.raises(ValueError):
        parse_cors_origins(value)


def test_cors_deduplicates_explicit_origins() -> None:
    assert parse_cors_origins(
        "http://localhost:3000/, https://example.com, http://localhost:3000"
    ) == ["http://localhost:3000", "https://example.com"]


def test_health_response_has_defensive_headers() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-request-id"]


def test_untrusted_correlation_header_is_not_echoed() -> None:
    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-ID": "client-controlled"})
    assert response.headers["x-request-id"] != "client-controlled"


def test_cors_preflight_allows_only_configured_origin() -> None:
    with TestClient(app) as client:
        allowed = client.options(
            "/v1/documents",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        denied = client.options(
            "/v1/documents",
            headers={
                "Origin": "https://attacker.example",
                "Access-Control-Request-Method": "POST",
            },
        )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in denied.headers
    assert denied.status_code == 400
