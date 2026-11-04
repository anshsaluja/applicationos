from fastapi.testclient import TestClient

from app.main import app
from app.persistence import DocumentRow, build_session_factory

client = TestClient(app)


def test_upload_text_document_returns_provenance_hash():
    response = client.post("/v1/documents", files={"file": ("requirements.txt", b"Proof of income is required.", "text/plain")})
    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "requirements.txt"
    assert body["text"] == "Proof of income is required."
    assert len(body["sha256"]) == 64


def test_duplicate_upload_is_idempotent_and_persisted():
    payload = b"Provide a valid government-issued ID."
    first = client.post("/v1/documents", files={"file": ("id.txt", payload, "text/plain")})
    second = client.post("/v1/documents", files={"file": ("id-copy.txt", payload, "text/plain")})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["sha256"] == second.json()["sha256"]

    factory = build_session_factory()
    with factory() as session:
        rows = session.query(DocumentRow).filter_by(sha256=first.json()["sha256"]).all()
        assert len(rows) == 1
        assert rows[0].text == payload.decode()


def test_rejects_unsupported_document_type():
    response = client.post("/v1/documents", files={"file": ("image.png", b"not-an-image", "image/png")})
    assert response.status_code == 415


def test_rejects_empty_document():
    response = client.post("/v1/documents", files={"file": ("empty.txt", b"", "text/plain")})
    assert response.status_code == 422


def test_uploaded_document_can_be_retrieved_with_same_provenance():
    payload = b"Evidence must include an official statement."
    uploaded = client.post("/v1/documents", files={"file": ("statement.txt", payload, "text/plain")})
    assert uploaded.status_code == 200
    document_id = uploaded.json()["id"]
    retrieved = client.get(f"/v1/documents/{document_id}")
    assert retrieved.status_code == 200
    assert retrieved.json() == uploaded.json()


def test_missing_document_returns_404():
    response = client.get("/v1/documents/00000000-0000-0000-0000-000000000001")
    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"


def test_stored_instructions_generate_pending_requirement_candidates():
    uploaded = client.post(
        "/v1/documents",
        files={"file": ("instructions.txt", b"Submit proof of address. Welcome!", "text/plain")},
    )
    assert uploaded.status_code == 200
    document_id = uploaded.json()["id"]
    response = client.get(f"/v1/documents/{document_id}/requirements")
    assert response.status_code == 200
    requirements = response.json()
    assert len(requirements) == 1
    assert requirements[0]["status"] == "pending"
    assert requirements[0]["evidence"] == []
    assert requirements[0]["description"] == "Submit proof of address."


def test_missing_document_requirement_candidates_return_404():
    response = client.get("/v1/documents/00000000-0000-0000-0000-000000000001/requirements")
    assert response.status_code == 404


def test_rejects_invalid_utf8_without_internal_server_error():
    response = client.post(
        "/v1/documents",
        files={"file": ("invalid.txt", b"\xff\xfe\x80", "text/plain")},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Plain-text document must be valid UTF-8"
