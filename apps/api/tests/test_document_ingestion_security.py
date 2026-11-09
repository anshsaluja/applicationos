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


def test_filename_removes_invisible_direction_and_format_controls():
    # These characters are not printable to users but can disguise extensions
    # or change how provenance filenames are rendered in the review UI.
    assert _safe_filename("report\u202egnp.exe.txt") == "reportgnp.exe.txt"
    assert _safe_filename("review\u200b-notes\u2066.txt") == "review-notes.txt"
    assert _safe_filename("Cafe\u0301.txt") == "Caf\u00e9.txt"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [b"hello\x00world", b"hello\x1b[31mworld", b"hello\x08world"])
async def test_reject_binary_and_terminal_control_characters(payload):
    upload = UploadFile(
        filename="instructions.txt",
        file=BytesIO(payload),
        headers=__import__("starlette.datastructures", fromlist=["Headers"]).Headers(
            {"content-type": "text/plain"}
        ),
    )
    with pytest.raises(HTTPException) as exc:
        await ingest_upload(upload)
    assert exc.value.status_code == 422
    assert exc.value.detail == "Document contains unsupported control characters"


@pytest.mark.asyncio
async def test_allow_normal_text_layout_whitespace():
    upload = UploadFile(
        filename="instructions.txt",
        file=BytesIO(b"First\tcolumn\r\nSecond line\n"),
        headers=__import__("starlette.datastructures", fromlist=["Headers"]).Headers(
            {"content-type": "text/plain"}
        ),
    )
    document = await ingest_upload(upload)
    assert document.text == "First\tcolumn\r\nSecond line"
