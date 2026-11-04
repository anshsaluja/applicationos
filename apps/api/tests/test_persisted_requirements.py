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
