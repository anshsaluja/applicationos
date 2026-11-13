"""Regression tests for safe PDF parsing and bounded extraction.

These tests isolate the parser to exercise malicious/degenerate document
behaviour without checking in potentially unsafe PDF fixtures.
"""

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile

from app.documents import MAX_EXTRACTED_CHARACTERS, ingest_upload


@pytest.mark.asyncio
async def test_pdf_parser_exception_does_not_leak_internal_details() -> None:
    upload = UploadFile(filename="broken.pdf", file=BytesIO(b"%PDF-malformed"), headers={"content-type": "application/pdf"})
    with patch("fitz.open", side_effect=RuntimeError("internal filesystem /secret/path")), pytest.raises(HTTPException) as caught:
            await ingest_upload(upload)
    assert caught.value.status_code == 422
    assert caught.value.detail == "Unable to parse PDF"
    assert "/secret/path" not in caught.value.detail


@pytest.mark.asyncio
async def test_pdf_extraction_limit_enforced_before_assembling_text() -> None:
    page = MagicMock()
    page.get_text.return_value = "x" * (MAX_EXTRACTED_CHARACTERS + 1)
    document = MagicMock()
    document.needs_pass = False
    document.__len__.return_value = 1
    document.__iter__.return_value = iter([page])
    manager = MagicMock()
    manager.__enter__.return_value = document
    with patch("fitz.open", return_value=manager):
        upload = UploadFile(filename="large.pdf", file=BytesIO(b"%PDF-test"), headers={"content-type": "application/pdf"})
        with pytest.raises(HTTPException) as caught:
            await ingest_upload(upload)
    assert caught.value.status_code == 413
    assert caught.value.detail == "Extracted PDF text exceeds limit"


@pytest.mark.asyncio
async def test_encrypted_pdf_is_rejected_before_page_iteration() -> None:
    document = MagicMock()
    document.needs_pass = True
    manager = MagicMock()
    manager.__enter__.return_value = document
    with patch("fitz.open", return_value=manager):
        upload = UploadFile(filename="encrypted.pdf", file=BytesIO(b"%PDF-test"), headers={"content-type": "application/pdf"})
        with pytest.raises(HTTPException) as caught:
            await ingest_upload(upload)
    assert caught.value.status_code == 422
    assert caught.value.detail == "Password-protected PDFs are not supported"
    document.__iter__.assert_not_called()
