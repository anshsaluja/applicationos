"""Regression tests for document upload size and provenance boundaries.

These tests require no database and exercise the same ingest_upload entry point
used by the HTTP document API.
"""

import asyncio
import hashlib
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.documents import MAX_DOCUMENT_BYTES, ingest_upload


def ingest(data: bytes, media_type: str = "text/plain", filename: str = "input.txt"):
    upload = UploadFile(
        file=BytesIO(data),
        filename=filename,
        headers=Headers({"content-type": media_type}),
    )
    return asyncio.run(ingest_upload(upload))


def test_rejects_oversized_plaintext_before_decoding():
    # Invalid UTF-8 beyond the limit must not turn a size violation into 422.
    data = b"A" * MAX_DOCUMENT_BYTES + b"\xff"
    with pytest.raises(HTTPException) as error:
        ingest(data)
    assert error.value.status_code == 413


def test_accepts_exact_upload_byte_limit_and_preserves_raw_hash():
    data = b"A" * MAX_DOCUMENT_BYTES
    with pytest.raises(HTTPException) as error:
        ingest(data)
    # The byte limit and extracted-character limit are separate safeguards.
    assert error.value.status_code == 413
    assert "text" in error.value.detail.lower()


@pytest.mark.parametrize("character", ["\u200b", "\u00ad", "\u2060", "\ufeff"])
def test_rejects_invisible_format_characters(character):
    with pytest.raises(HTTPException) as error:
        ingest(("Submit proof " + character + "of address").encode("utf-8"))
    assert error.value.status_code == 422
    assert "formatting" in error.value.detail.lower()


def test_filename_sanitization_does_not_change_document_digest():
    data = b"  Submit proof of address  "
    result = ingest(data, filename="../nested/hidden\u200b.txt")
    assert result.filename == "hidden.txt"
    assert result.text == "Submit proof of address"
    assert result.sha256 == hashlib.sha256(data).hexdigest()


def test_accepts_maximum_extracted_text_and_hashes_original_bytes():
    # The extracted-character ceiling is inclusive and distinct from the 8 MiB
    # upload limit. A valid boundary document must remain ingestible.
    from app.documents import MAX_EXTRACTED_CHARACTERS

    data = b"A" * MAX_EXTRACTED_CHARACTERS
    result = ingest(data, filename="boundary.txt")
    assert len(result.text) == MAX_EXTRACTED_CHARACTERS
    assert result.sha256 == hashlib.sha256(data).hexdigest()


def test_rejects_one_character_beyond_extracted_text_limit():
    from app.documents import MAX_EXTRACTED_CHARACTERS

    data = b"A" * (MAX_EXTRACTED_CHARACTERS + 1)
    with pytest.raises(HTTPException) as error:
        ingest(data)
    assert error.value.status_code == 413
    assert "text" in error.value.detail.lower()
