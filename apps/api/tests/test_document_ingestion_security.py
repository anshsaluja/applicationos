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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected_detail"),
    [
        ("Approve\u202eDENY".encode("utf-8"), "Document contains unsupported bidirectional formatting"),
        ("Approve\u2066DENY\u2069".encode("utf-8"), "Document contains unsupported bidirectional formatting"),
        ("require\u200bment".encode("utf-8"), "Document contains unsupported Unicode formatting"),
        ("confi\u00addential".encode("utf-8"), "Document contains unsupported Unicode formatting"),
    ],
)
async def test_reject_invisible_or_directional_evidence_text(payload, expected_detail):
    """A reviewer must not see visually misleading evidence or requirements."""
    from starlette.datastructures import Headers

    upload = UploadFile(
        filename="evidence.txt",
        file=BytesIO(payload),
        headers=Headers({"content-type": "text/plain"}),
    )
    with pytest.raises(HTTPException) as exc:
        await ingest_upload(upload)
    assert exc.value.status_code == 422
    assert exc.value.detail == expected_detail


@pytest.mark.asyncio
@pytest.mark.parametrize("media_type", ["text/plain; charset=utf-8", "Text/Plain; Charset=\"UTF-8\"", "text/plain; charset=UTF8"])
async def test_accept_explicit_utf8_text_content_type(media_type):
    from starlette.datastructures import Headers

    upload = UploadFile(filename="requirements.txt", file=BytesIO("Résumé required".encode("utf-8")), headers=Headers({"content-type": media_type}))
    document = await ingest_upload(upload)
    assert document.media_type == "text/plain"
    assert document.text == "Résumé required"


@pytest.mark.asyncio
@pytest.mark.parametrize("media_type", ["text/plain; charset=latin-1", "text/plain; boundary=ignored", "text/plain; charset=utf-8; charset=latin-1", "text/plain; invalid"])
async def test_reject_unsupported_or_ambiguous_content_type_parameters(media_type):
    from starlette.datastructures import Headers

    upload = UploadFile(filename="requirements.txt", file=BytesIO(b"Submit a resume"), headers=Headers({"content-type": media_type}))
    with pytest.raises(HTTPException) as exc:
        await ingest_upload(upload)
    assert exc.value.status_code == 415
