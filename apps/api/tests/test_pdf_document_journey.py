"""Real PDF-to-requirements integration coverage using PostgreSQL and HTTP.

Unlike mocked browser tests, these exercise parsing, durable storage,
source provenance, conservative extraction, and idempotent persistence.
"""
from uuid import uuid4

import fitz
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_real_pdf_document_to_persisted_requirements_with_provenance():
    unique = str(uuid4())
    first_instruction = f"Applicant must provide proof of residence {unique}."
    second_instruction = "Submit a current bank statement."
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), first_instruction)
    page.insert_text((72, 100), second_instruction)
    page.insert_text((72, 128), "Welcome to the application portal.")
    payload = pdf.tobytes()
    pdf.close()

    upload = client.post(
        "/v1/documents",
        files={"file": ("sample-instructions.pdf", payload, "application/pdf")},
    )
    assert upload.status_code == 200
    document = upload.json()
    document_id = document["id"]
    assert first_instruction in document["text"]

    sources = client.get(f"/v1/documents/{document_id}/requirement-sources")
    assert sources.status_code == 200
    source_rows = sources.json()
    assert len(source_rows) == 2
    assert {row["instruction_excerpt"] for row in source_rows} == {
        first_instruction, second_instruction
    }
    assert all(row["source_document_id"] == document_id for row in source_rows)
    assert all(row["source_label"] == "sample-instructions.pdf" for row in source_rows)
    assert all(row["status"] == "pending" for row in source_rows)
    assert all(row["satisfaction_evidence"] == [] for row in source_rows)

    first = client.post(f"/v1/documents/{document_id}/requirements/persist")
    second = client.post(f"/v1/documents/{document_id}/requirements/persist")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    saved = first.json()
    assert len(saved["requirements"]) == 2
    assert {item["id"] for item in saved["requirements"]} == {
        row["requirement_id"] for row in source_rows
    }
    assert all(item["status"] == "pending" for item in saved["requirements"])
    assert all(item["evidence"] == [] for item in saved["requirements"])

    reloaded = client.get(
        f"/v1/workspaces/{saved['workspace_id']}/requirements"
    )
    assert reloaded.status_code == 200
    assert reloaded.json() == saved
