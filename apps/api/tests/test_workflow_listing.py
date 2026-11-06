"""HTTP and PostgreSQL coverage for bounded workflow inspection."""
from uuid import uuid4

from fastapi.testclient import TestClient

from app.domain.workflows import WorkflowState
from app.main import app
from app.persistence import WorkflowRepository, build_session_factory, session_scope


def test_workflow_list_is_read_only_deterministic_and_paginated():
    ids = [uuid4() for _ in range(3)]
    with session_scope(build_session_factory()) as session:
        repository = WorkflowRepository(session)
        for action_id in ids:
            repository.create(
                WorkflowState(action_id=action_id, idempotency_key=f"listing:{action_id}")
            )

    client = TestClient(app)
    response = client.get("/v1/workflows", params={"limit": 100})
    assert response.status_code == 200
    rows = response.json()
    listed_ids = [row["action_id"] for row in rows]
    assert listed_ids == sorted(listed_ids)
    for action_id in ids:
        assert str(action_id) in listed_ids
        assert next(row for row in rows if row["action_id"] == str(action_id))["status"] == "pending"

    first = client.get("/v1/workflows", params={"limit": 1, "offset": 0})
    second = client.get("/v1/workflows", params={"limit": 1, "offset": 1})
    assert first.status_code == second.status_code == 200
    assert first.json()[0]["action_id"] == listed_ids[0]
    assert second.json()[0]["action_id"] == listed_ids[1]


def test_workflow_list_rejects_unbounded_pagination():
    client = TestClient(app)
    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"offset": 10001}):
        assert client.get("/v1/workflows", params=params).status_code == 422
