"""HTTP regression coverage for durable pending workflow intent creation."""
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


def test_create_pending_workflow_is_idempotent_and_readable():
    client = TestClient(app)
    action_id = str(uuid4())
    payload = {
        "action_id": action_id,
        "idempotency_key": f"test:{action_id}",
        "max_attempts": 2,
    }
    first = client.post("/v1/workflows", json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "pending"
    assert first.json()["attempt"] == 0

    duplicate = client.post("/v1/workflows", json=payload)
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json() == first.json()

    fetched = client.get(f"/v1/workflows/{action_id}")
    assert fetched.status_code == 200
    assert fetched.json() == first.json()


def test_create_workflow_rejects_conflicting_retry_policy_and_bad_inputs():
    client = TestClient(app)
    action_id = str(uuid4())
    payload = {
        "action_id": action_id,
        "idempotency_key": f"test:{action_id}",
        "max_attempts": 2,
    }
    assert client.post("/v1/workflows", json=payload).status_code == 200

    conflict = client.post("/v1/workflows", json={**payload, "max_attempts": 3})
    assert conflict.status_code == 409

    invalid = client.post("/v1/workflows", json={**payload, "max_attempts": 0})
    assert invalid.status_code == 422

    original = client.get(f"/v1/workflows/{action_id}")
    assert original.json()["max_attempts"] == 2
