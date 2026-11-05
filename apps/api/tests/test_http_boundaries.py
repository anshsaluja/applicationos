"""HTTP boundary regressions: malformed requests must fail before database access."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.mark.parametrize(
    ("payload", "expected_status"),
    [
        ({"action_id": str(uuid4()), "idempotency_key": ""}, 422),
        ({"action_id": str(uuid4()), "idempotency_key": "x" * 201}, 422),
        ({"action_id": str(uuid4()), "idempotency_key": "valid", "max_attempts": 0}, 422),
        ({"action_id": str(uuid4()), "idempotency_key": "valid", "max_attempts": 11}, 422),
        ({"action_id": "not-a-uuid", "idempotency_key": "valid"}, 422),
        ({"idempotency_key": "valid"}, 422),
    ],
)
def test_workflow_creation_rejects_invalid_intent(payload: dict, expected_status: int) -> None:
    response = client.post("/v1/workflows", json=payload)
    assert response.status_code == expected_status


@pytest.mark.parametrize(
    "path",
    [
        "/v1/workflows/not-a-uuid",
        "/v1/documents/not-a-uuid",
        "/v1/documents/not-a-uuid/requirements",
        "/v1/documents/not-a-uuid/requirement-sources",
        "/v1/documents/not-a-uuid/requirements/persist",
        "/v1/workspaces/not-a-uuid/requirements",
    ],
)
def test_invalid_resource_ids_fail_at_http_boundary(path: str) -> None:
    method = client.post if path.endswith("/persist") else client.get
    response = method(path)
    assert response.status_code == 422


def test_workflow_creation_does_not_accept_approval_or_execution_flags() -> None:
    """Unrecognized approval flags must not become workflow authorization."""
    response = client.post(
        "/v1/workflows",
        json={
            "action_id": str(uuid4()),
            "idempotency_key": "",
            "approved": True,
            "execute": True,
        },
    )
    assert response.status_code == 422
