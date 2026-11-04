from uuid import uuid4

from fastapi.testclient import TestClient

from app.api import get_session_factory
from app.documents import IngestedDocument
from app.main import app
from app.persistence import DocumentRepository, session_scope


def test_requirement_sources_are_attributed_to_stored_instructions():
    source_id = uuid4()
    text = "You must provide proof of address. Submit a valid ID."
    with session_scope(get_session_factory()) as session:
        row = DocumentRepository(session).add(
            IngestedDocument(id=source_id, filename="instructions.txt", text=text, sha256="a" * 64)
        )
        document_id = row.id
    response = TestClient(app).get(f"/v1/documents/{document_id}/requirement-sources")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 2
    assert all(item["source_document_id"] == str(document_id) for item in items)
    assert all(item["source_label"] == "instructions.txt" for item in items)
    assert all(item["status"] == "pending" for item in items)
    assert all(item["satisfaction_evidence"] == [] for item in items)
    assert items[0]["instruction_excerpt"] == "You must provide proof of address."


def test_requirement_sources_missing_document_returns_404():
    response = TestClient(app).get(f"/v1/documents/{uuid4()}/requirement-sources")
    assert response.status_code == 404
