"""Upload validation must reject unsafe inputs before database access."""
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile

from app.documents import MAX_EXTRACTED_CHARACTERS, _safe_filename, ingest_upload


@pytest.mark.asyncio
async def test_reject_pdf_with_spoofed_content_type():
    upload = UploadFile(filename="fake.pdf", file=BytesIO(b"not actually a pdf"))
    upload.headers = __import__("starlette.datastructures", fromlist=["Headers"]).Headers(
        {"content-type": "application/pdf"}
    )
    with pytest.raises(HTTPException) as exc:
        await ingest_upload(upload)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_reject_text_with_excessive_extracted_characters():
    upload = UploadFile(
        filename="large.txt",
        file=BytesIO(b"x" * (MAX_EXTRACTED_CHARACTERS + 1)),
        headers=__import__("starlette.datastructures", fromlist=["Headers"]).Headers(
            {"content-type": "text/plain"}
        ),
    )
    with pytest.raises(HTTPException) as exc:
        await ingest_upload(upload)
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_upload_filename_is_sanitized():
    upload = UploadFile(
        filename="../private\\instructions\x00.txt",
        file=BytesIO(b"Please provide an identity document."),
        headers=__import__("starlette.datastructures", fromlist=["Headers"]).Headers(
            {"content-type": "text/plain"}
        ),
    )
    document = await ingest_upload(upload)
    assert document.filename == "instructions.txt"
    assert document.text == "Please provide an identity document."


def test_filename_is_bounded_and_never_empty():
    assert _safe_filename("a" * 300) == "a" * 240
    assert _safe_filename("\x00/") == "document"
