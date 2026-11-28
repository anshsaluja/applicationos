"""PostgreSQL-backed HTTP tests for the disabled-by-default local approval boundary."""
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


def _reviewable(client):
    action = str(uuid4())
    response = client.post("/v1/workflows", json={
        "action_id": action, "idempotency_key": f"decision:{action}",
    })
    assert response.status_code == 200, response.text
    response = client.post(f"/v1/workflows/{action}/request-review")
    assert response.status_code == 200, response.text
    return action


def test_review_denied_without_explicit_operator_configuration(monkeypatch):
    monkeypatch.delenv("APPLICATIONOS_REVIEW_TOKEN", raising=False)
    monkeypatch.delenv("APPLICATIONOS_REVIEWER_ID", raising=False)
    client = TestClient(app)
    action = _reviewable(client)
    result = client.post(f"/v1/workflows/{action}/decision",
                         json={"decision": "approved"}, headers={"x-review-token": "anything"})
    assert result.status_code == 403
    assert client.get(f"/v1/workflows/{action}").json()["status"] == "awaiting_approval"


def test_approved_review_is_durable_and_does_not_execute(monkeypatch):
    monkeypatch.setenv("APPLICATIONOS_REVIEW_TOKEN", "local-test-secret")
    monkeypatch.setenv("APPLICATIONOS_REVIEWER_ID", "local-operator")
    client = TestClient(app)
    action = _reviewable(client)
    assert client.post(f"/v1/workflows/{action}/decision",
                       json={"decision": "approved"}, headers={"x-review-token": "wrong"}).status_code == 403
    result = client.post(f"/v1/workflows/{action}/decision",
                         json={"decision": "approved"}, headers={"x-review-token": "local-test-secret"})
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "ready"
    assert result.json()["attempt"] == 0
    assert client.get(f"/v1/workflows/{action}").json()["status"] == "ready"
    assert client.post(f"/v1/workflows/{action}/decision",
                       json={"decision": "rejected", "reason": "late"},
                       headers={"x-review-token": "local-test-secret"}).status_code == 409


def test_rejection_requires_reason_and_fails_closed(monkeypatch):
    monkeypatch.setenv("APPLICATIONOS_REVIEW_TOKEN", "local-test-secret")
    monkeypatch.setenv("APPLICATIONOS_REVIEWER_ID", "local-operator")
    client = TestClient(app)
    action = _reviewable(client)
    url = f"/v1/workflows/{action}/decision"
    headers = {"x-review-token": "local-test-secret"}
    assert client.post(url, json={"decision": "rejected"}, headers=headers).status_code == 409
    assert client.get(f"/v1/workflows/{action}").json()["status"] == "awaiting_approval"
    result = client.post(url, json={"decision": "rejected", "reason": "insufficient evidence"}, headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "failed"
