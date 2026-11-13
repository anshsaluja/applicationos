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



def test_rejects_pdf_exceeding_page_limit():
    import fitz

    pdf = fitz.open()
    for _ in range(101):
        pdf.new_page()
    payload = pdf.tobytes()
    pdf.close()

    response = client.post(
        "/v1/documents",
        files={"file": ("too-many-pages.pdf", payload, "application/pdf")},
    )
    assert response.status_code == 413
    assert response.json()["detail"] == "PDF exceeds 100-page limit"


def test_rejects_password_protected_pdf():
    import fitz

    pdf = fitz.open()
    pdf.new_page()
    payload = pdf.tobytes(
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner-password",
        user_pw="reader-password",
    )
    pdf.close()

    response = client.post(
        "/v1/documents",
        files={"file": ("locked.pdf", payload, "application/pdf")},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Password-protected PDFs are not supported"


def test_rejects_excessive_extracted_pdf_text(monkeypatch):
    from app import documents

    class FakePage:
        def get_text(self):
            return "A" * (documents.MAX_EXTRACTED_CHARACTERS + 1)

    class FakePDF:
        needs_pass = False

        def __len__(self):
            return 1

        def __iter__(self):
            return iter([FakePage()])

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    import fitz

    monkeypatch.setattr(fitz, "open", lambda **_kwargs: FakePDF())
    response = client.post(
        "/v1/documents",
        files={"file": ("expanded.pdf", b"%PDF-1.7", "application/pdf")},
    )
    assert response.status_code == 413
    assert response.json()["detail"] == "Extracted PDF text exceeds limit"


def test_pdf_extraction_limit_includes_interpage_separators(monkeypatch):
    """Page separators count toward the same bound as extracted page text."""
    import fitz
    import pytest
    from fastapi import HTTPException

    from app import documents

    class FakePage:
        def __init__(self, text):
            self.text = text

        def get_text(self):
            return self.text

    class FakePDF:
        needs_pass = False

        def __init__(self, pages):
            self.pages = [FakePage(text) for text in pages]

        def __len__(self):
            return len(self.pages)

        def __iter__(self):
            return iter(self.pages)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    # Two individually valid pages exceed the maximum only after the
    # newline separator is inserted.
    pages = ["A" * (documents.MAX_EXTRACTED_CHARACTERS - 1), "B"]
    monkeypatch.setattr(fitz, "open", lambda **_kwargs: FakePDF(pages))
    with pytest.raises(HTTPException) as exc:
        documents._extract_pdf(b"%PDF-1.7")
    assert exc.value.status_code == 413
    assert exc.value.detail == "Extracted PDF text exceeds limit"

    # Exactly at the cap (including separators) must still be accepted.
    pages = ["A" * (documents.MAX_EXTRACTED_CHARACTERS - 3), "B"]
    monkeypatch.setattr(fitz, "open", lambda **_kwargs: FakePDF(pages))
    extracted = documents._extract_pdf(b"%PDF-1.7")
    assert len(extracted) == documents.MAX_EXTRACTED_CHARACTERS
    assert extracted.endswith("\n\nB")
