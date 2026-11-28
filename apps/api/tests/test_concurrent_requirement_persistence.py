"""PostgreSQL concurrency regression for document requirement persistence.

Requires the disposable pgvector/PostgreSQL database used by API CI.
"""
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.main import app


def test_simultaneous_requirement_persistence_is_idempotent() -> None:
    """Two requests must return the same workspace without duplicate rows."""
    instructions = (
        f"Application reference {uuid4()}.\n"
        "You must provide proof of income.\n"
        "You must submit a government-issued identification document.\n"
    )
    with TestClient(app) as client:
        uploaded = client.post(
            "/v1/documents",
            files={"file": ("concurrent-requirements.txt", instructions.encode(), "text/plain")},
        )
        assert uploaded.status_code == 200, uploaded.text
        document_id = uploaded.json()["id"]

        def persist(_: int) -> dict:
            # Each request gets its own database session through the API.
            response = client.post(f"/v1/documents/{document_id}/requirements/persist")
            assert response.status_code == 200, response.text
            return response.json()

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(persist, range(12)))

        workspace_ids = {result["workspace_id"] for result in results}
        assert len(workspace_ids) == 1
        workspace_id = next(iter(workspace_ids))
        UUID(workspace_id)
        persisted = client.get(f"/v1/workspaces/{workspace_id}/requirements")
        assert persisted.status_code == 200, persisted.text
        stored = persisted.json()["requirements"]
        assert stored, "Fixture must produce real extraction candidates"
        stored_ids = [requirement["id"] for requirement in stored]
        assert len(stored_ids) == len(set(stored_ids))
        for result in results:
            assert {item["id"] for item in result["requirements"]} == set(stored_ids)
        assert all(item["status"] == "pending" for item in stored)
