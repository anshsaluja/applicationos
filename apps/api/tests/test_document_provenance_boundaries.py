"""Boundary tests for document provenance and filename normalization.

These exercise ingestion directly without requiring a database.
"""
import asyncio
import hashlib
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.documents import ingest_upload


def upload(payload: bytes, filename: str, content_type: str = "text/plain") -> UploadFile:
    return UploadFile(
        filename=filename,
        file=BytesIO(payload),
        headers=Headers({"content-type": content_type}),
    )


def test_provenance_hash_uses_original_bytes_not_decoded_text():
    raw = b"\xef\xbb\xbfSubmit proof of address.\n"
    document = asyncio.run(ingest_upload(upload(raw, "instructions.txt")))
    assert document.text == "Submit proof of address."
    assert document.sha256 == hashlib.sha256(raw).hexdigest()
    assert document.sha256 != hashlib.sha256(document.text.encode()).hexdigest()


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("../../secret.txt", "secret.txt"),
        (r"C:\\private\\identity.txt", "identity.txt"),
        ("\u202eunsafe.txt", "unsafe.txt"),
        ("...", "document"),
        ("  ", "document"),
    ],
)
def test_uploaded_filename_is_display_only_basename(filename: str, expected: str):
    document = asyncio.run(ingest_upload(upload(b"Provide an ID.", filename)))
    assert document.filename == expected


@pytest.mark.parametrize(
    "content_type",
    [
        "application/pdf; charset=utf-8",
        "text/plain; charset=latin-1",
        "text/plain; charset=utf-8; charset=utf-8",
        "text/plain; charset=\"utf-8",
    ],
)
def test_ambiguous_or_unsupported_media_type_parameters_fail_closed(content_type: str):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ingest_upload(upload(b"Provide an ID.", "id.txt", content_type)))
    assert exc.value.status_code == 415


def test_valid_explicit_utf8_charset_is_accepted():
    document = asyncio.run(
        ingest_upload(upload(b"Submit proof of income.", "income.txt", "text/plain; charset=UTF-8"))
    )
    assert document.text == "Submit proof of income."
