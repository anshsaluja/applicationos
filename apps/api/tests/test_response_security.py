"""Regression checks for sensitive API response caching and browser hardening."""
from fastapi.testclient import TestClient

from app.main import app


def test_document_and_workflow_api_responses_are_not_cacheable():
    client = TestClient(app)
    for path in ("/v1/documents/not-a-uuid", "/v1/workflows/not-a-uuid"):
        response = client.get(path)
        assert response.status_code == 422
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"


def test_health_remains_available_with_security_headers():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
