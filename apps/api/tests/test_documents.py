from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_upload_text_document_returns_provenance_hash():
    response = client.post("/v1/documents", files={"file": ("requirements.txt", b"Proof of income is required.", "text/plain")})
    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "requirements.txt"
    assert body["text"] == "Proof of income is required."
    assert len(body["sha256"]) == 64


def test_rejects_unsupported_document_type():
    response = client.post("/v1/documents", files={"file": ("image.png", b"not-an-image", "image/png")})
    assert response.status_code == 415


def test_rejects_empty_document():
    response = client.post("/v1/documents", files={"file": ("empty.txt", b"", "text/plain")})
    assert response.status_code == 422
