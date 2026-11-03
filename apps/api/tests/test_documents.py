from fastapi.testclient import TestClient

from app.main import app
from app.persistence import DocumentRow, get_session_factory if False else build_session_factory

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
