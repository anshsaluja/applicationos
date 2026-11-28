"""HTTP integration coverage for read-only durable workflow status."""
from uuid import uuid4

from fastapi.testclient import TestClient

from app.domain.workflows import WorkflowState, WorkflowStatus
from app.main import app
from app.persistence import WorkflowRepository, build_session_factory, session_scope


def test_workflow_checkpoint_endpoint_reads_persisted_state():
    action_id = uuid4()
    with session_scope(build_session_factory()) as session:
        repo = WorkflowRepository(session)
        repo.create(WorkflowState(action_id=action_id, idempotency_key=f"http:{action_id}"))
        repo.advance(action_id, WorkflowStatus.AWAITING_APPROVAL)

    response = TestClient(app).get(f"/v1/workflows/{action_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["action_id"] == str(action_id)
    assert body["status"] == "awaiting_approval"
    assert body["attempt"] == 0
    assert body["max_attempts"] == 3
    assert body["idempotency_key"] == f"http:{action_id}"


def test_workflow_checkpoint_endpoint_returns_404_for_unknown_action():
    response = TestClient(app).get(f"/v1/workflows/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Workflow not found"
