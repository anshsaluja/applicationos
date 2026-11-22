"""Bounded upload and byte-provenance regression checks.

These tests intentionally exercise ingestion without a database or network.
"""

import hashlib
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.documents import MAX_DOCUMENT_BYTES, ingest_upload


def text_upload(payload: bytes) -> UploadFile:
    return UploadFile(
        filename="evidence.txt",
        file=BytesIO(payload),
        headers=Headers({"content-type": "text/plain; charset=utf-8"}),
    )


@pytest.mark.asyncio
async def test_exact_maximum_upload_size_is_accepted_with_original_digest():
    payload = b"x" * MAX_DOCUMENT_BYTES
    document = await ingest_upload(text_upload(payload))
    assert len(document.text) == MAX_DOCUMENT_BYTES
    assert document.sha256 == hashlib.sha256(payload).hexdigest()


@pytest.mark.asyncio
async def test_one_byte_above_maximum_is_rejected_before_extraction():
    with pytest.raises(HTTPException) as error:
        await ingest_upload(text_upload(b"x" * (MAX_DOCUMENT_BYTES + 1)))
    assert error.value.status_code == 413


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [b"\xff", b"valid\xc3(", b"\xed\xa0\x80"])
async def test_invalid_utf8_never_becomes_persisted_evidence(payload: bytes):
    with pytest.raises(HTTPException) as error:
        await ingest_upload(text_upload(payload))
    assert error.value.status_code == 422
    assert error.value.detail == "Plain-text document must be valid UTF-8"


@pytest.mark.asyncio
async def test_whitespace_only_document_is_rejected():
    with pytest.raises(HTTPException) as error:
        await ingest_upload(text_upload(b"\t \r\n  "))
    assert error.value.status_code == 422
    assert error.value.detail == "No extractable text found"
