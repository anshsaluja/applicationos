from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_persisted_requirements_are_idempotent_and_pending() -> None:
    uploaded = client.post(
        "/v1/documents",
        files={"file": ("instructions.txt", b"You must provide proof of address. Submit a photo ID.", "text/plain")},
    )
    assert uploaded.status_code == 200
    document_id = uploaded.json()["id"]
    first = client.post(f"/v1/documents/{document_id}/requirements/persist")
    second = client.post(f"/v1/documents/{document_id}/requirements/persist")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    requirements = first.json()["requirements"]
    assert len(requirements) == 2
    assert all(item["status"] == "pending" and item["evidence"] == [] for item in requirements)


def test_persist_requirements_missing_document() -> None:
    response = client.post("/v1/documents/00000000-0000-0000-0000-000000000001/requirements/persist")
    assert response.status_code == 404


def test_workspace_read_returns_persisted_requirements() -> None:
    uploaded = client.post(
        "/v1/documents",
        files={"file": ("workspace-read.txt", b"You must submit a bank statement.", "text/plain")},
    )
    assert uploaded.status_code == 200
    document_id = uploaded.json()["id"]
    persisted = client.post(f"/v1/documents/{document_id}/requirements/persist")
    assert persisted.status_code == 200
    workspace_id = persisted.json()["workspace_id"]
    read = client.get(f"/v1/workspaces/{workspace_id}/requirements")
    assert read.status_code == 200
    assert read.json() == persisted.json()


def test_workspace_read_missing_workspace() -> None:
    response = client.get("/v1/workspaces/00000000-0000-0000-0000-000000000001/requirements")
    assert response.status_code == 404
