"""Fail-closed API security regressions that do not require a running database."""

from fastapi.testclient import TestClient

from app.main import app


def test_sensitive_api_errors_are_not_cacheable() -> None:
    client = TestClient(app)
    response = client.get("/v1/documents/not-a-uuid")
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_review_decision_denied_without_configured_operator(monkeypatch) -> None:
    monkeypatch.delenv("APPLICATIONOS_REVIEW_TOKEN", raising=False)
    monkeypatch.delenv("APPLICATIONOS_REVIEWER_ID", raising=False)
    client = TestClient(app)
    response = client.post(
        "/v1/workflows/00000000-0000-0000-0000-000000000001/decision",
        json={"decision": "approved"},
        headers={"X-Review-Token": "attacker-supplied-token"},
    )
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
