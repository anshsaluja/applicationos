"""Durable review-request HTTP integration tests (PostgreSQL required)."""
from uuid import uuid4

from fastapi.testclient import TestClient

from app.domain.workflows import WorkflowStatus
from app.main import app
from app.persistence import WorkflowRepository, build_session_factory, session_scope


def test_request_review_is_persisted_and_idempotent():
    client = TestClient(app)
    action_id = str(uuid4())
    created = client.post("/v1/workflows", json={
        "action_id": action_id,
        "idempotency_key": f"review:{action_id}",
        "max_attempts": 2,
    })
    assert created.status_code == 200, created.text
    assert created.json()["status"] == "pending"

    first = client.post(f"/v1/workflows/{action_id}/request-review")
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "awaiting_approval"
    assert first.json()["attempt"] == 0

    duplicate = client.post(f"/v1/workflows/{action_id}/request-review")
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json() == first.json()
    assert client.get(f"/v1/workflows/{action_id}").json() == first.json()


def test_request_review_unknown_action_returns_404():
    response = TestClient(app).post(f"/v1/workflows/{uuid4()}/request-review")
    assert response.status_code == 404


def test_request_review_cannot_reset_approved_workflow():
    client = TestClient(app)
    action_id = uuid4()
    response = client.post("/v1/workflows", json={
        "action_id": str(action_id),
        "idempotency_key": f"review-terminal:{action_id}",
    })
    assert response.status_code == 200, response.text
    assert client.post(f"/v1/workflows/{action_id}/request-review").status_code == 200

    # Internal persistence is used to prepare the terminal state; this test
    # does not introduce an unauthenticated approval HTTP endpoint.
    with session_scope(build_session_factory()) as session:
        repo = WorkflowRepository(session)
        repo.advance(action_id, WorkflowStatus.FAILED, error="Review rejected")

    rejected = client.post(f"/v1/workflows/{action_id}/request-review")
    assert rejected.status_code == 409
    current = client.get(f"/v1/workflows/{action_id}").json()
    assert current["status"] == "failed"
    assert current["attempt"] == 0
