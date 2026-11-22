"""PDF resource-limit regressions without large or untrusted fixture files."""

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.documents import MAX_EXTRACTED_CHARACTERS, MAX_PDF_PAGES, ingest_upload


def pdf_upload() -> UploadFile:
    return UploadFile(
        filename="evidence.pdf",
        file=BytesIO(b"%PDF-synthetic"),
        headers=Headers({"content-type": "application/pdf"}),
    )


def mocked_pdf(pages: list[MagicMock]) -> MagicMock:
    document = MagicMock()
    document.needs_pass = False
    document.__len__.return_value = len(pages)
    document.__iter__.return_value = iter(pages)
    manager = MagicMock()
    manager.__enter__.return_value = document
    return manager


@pytest.mark.asyncio
async def test_page_limit_rejects_before_extracting_any_page() -> None:
    first_page = MagicMock()
    manager = mocked_pdf([first_page] * (MAX_PDF_PAGES + 1))
    with patch("fitz.open", return_value=manager), pytest.raises(HTTPException) as error:
        await ingest_upload(pdf_upload())
    assert error.value.status_code == 413
    assert error.value.detail == "PDF exceeds 100-page limit"
    first_page.get_text.assert_not_called()


@pytest.mark.asyncio
async def test_pdf_join_separator_counts_toward_extraction_limit() -> None:
    first_page = MagicMock()
    first_page.get_text.return_value = "a" * (MAX_EXTRACTED_CHARACTERS - 1)
    second_page = MagicMock()
    second_page.get_text.return_value = "b"
    manager = mocked_pdf([first_page, second_page])
    with patch("fitz.open", return_value=manager), pytest.raises(HTTPException) as error:
        await ingest_upload(pdf_upload())
    assert error.value.status_code == 413
    assert error.value.detail == "Extracted PDF text exceeds limit"


@pytest.mark.asyncio
async def test_pdf_exact_joined_text_limit_preserves_original_digest() -> None:
    import hashlib

    first_page = MagicMock()
    first_page.get_text.return_value = "a" * (MAX_EXTRACTED_CHARACTERS - 3)
    second_page = MagicMock()
    second_page.get_text.return_value = "b"
    manager = mocked_pdf([first_page, second_page])
    with patch("fitz.open", return_value=manager):
        document = await ingest_upload(pdf_upload())
    assert len(document.text) == MAX_EXTRACTED_CHARACTERS
    assert document.text.endswith("\n\nb")
    assert document.sha256 == hashlib.sha256(b"%PDF-synthetic").hexdigest()
