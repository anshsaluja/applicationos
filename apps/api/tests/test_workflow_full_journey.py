"""PostgreSQL-backed HTTP journey: durable intent, human gate, and recovery.

This intentionally stops short of external execution. No HTTP endpoint may
claim an action was executed until an authenticated worker exists.
"""
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.persistence import ApprovalRepository, WorkflowRepository, build_session_factory, session_scope
from app.domain.workflows import WorkflowStatus


def test_approved_checkpoint_survives_restart_and_recovery(monkeypatch):
    monkeypatch.setenv("APPLICATIONOS_REVIEW_TOKEN", "journey-test-token")
    monkeypatch.setenv("APPLICATIONOS_REVIEWER_ID", "journey-reviewer")
    client = TestClient(app)
    action = uuid4()
    url = f"/v1/workflows/{action}"
    key = f"journey:{action}"

    created = client.post("/v1/workflows", json={
        "action_id": str(action), "idempotency_key": key, "max_attempts": 2,
    })
    assert created.status_code == 200, created.text
    assert created.json()["status"] == "pending"
    assert client.post("/v1/workflows", json={
        "action_id": str(action), "idempotency_key": key, "max_attempts": 2,
    }).json() == created.json()

    # Unauthorized decisions never change the checkpoint or approval record.
    assert client.post(f"{url}/decision", json={"decision": "approved"},
                       headers={"x-review-token": "journey-test-token"}).status_code == 409
    assert client.post(f"{url}/request-review").json()["status"] == "awaiting_approval"
    assert client.post(f"{url}/decision", json={"decision": "approved"},
                       headers={"x-review-token": "incorrect"}).status_code == 403
    assert client.get(url).json()["status"] == "awaiting_approval"

    approved = client.post(f"{url}/decision", json={"decision": "approved"},
                           headers={"x-review-token": "journey-test-token"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "ready"
    assert approved.json()["attempt"] == 0
    assert client.get(url).json()["status"] == "ready"

    # Simulate an independent worker process using fresh database sessions.
    factory = build_session_factory()
    with session_scope(factory) as session:
        decision = ApprovalRepository(session).get(action)
        assert decision.reviewer_id == "journey-reviewer"
        running = WorkflowRepository(session).advance(action, WorkflowStatus.RUNNING)
        assert running.attempt == 1
    with session_scope(factory) as session:
        failed = WorkflowRepository(session).recover_interrupted(action, reason="worker terminated")
        assert failed.status == WorkflowStatus.FAILED
        assert failed.attempt == 1
    with session_scope(factory) as session:
        repository = WorkflowRepository(session)
        assert repository.advance(action, WorkflowStatus.READY).status == WorkflowStatus.READY
        assert repository.advance(action, WorkflowStatus.RUNNING).attempt == 2
        assert repository.advance(action, WorkflowStatus.SUCCEEDED).status == WorkflowStatus.SUCCEEDED
    assert client.get(url).json()["status"] == "succeeded"
    assert client.get(url).json()["attempt"] == 2
    assert client.post(f"{url}/request-review").status_code == 409
