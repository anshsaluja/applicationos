"""Database-independent tests for the document trust boundary."""

import asyncio
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile

from app.documents import ingest_upload


def ingest(payload: bytes, *, filename: str = "instructions.txt"):
    upload = UploadFile(file=BytesIO(payload), filename=filename, headers=None)
    # UploadFile without headers defaults to application/octet-stream;
    # attach a real multipart Content-Type for the ingestion boundary.
    from starlette.datastructures import Headers

    upload.headers = Headers({"content-type": "text/plain"})
    return asyncio.run(ingest_upload(upload))


@pytest.mark.parametrize("character", ["\u202a", "\u202b", "\u202c", "\u202d", "\u202e", "\u2066", "\u2067", "\u2068", "\u2069"])
def test_rejects_bidirectional_controls(character):
    with pytest.raises(HTTPException) as error:
        ingest(("Submit proof " + character + "of income").encode("utf-8"))
    assert error.value.status_code == 422
    assert "bidirectional" in error.value.detail


@pytest.mark.parametrize("character", ["\x00", "\x01", "\x1b", "\x7f"])
def test_rejects_nonprinting_controls(character):
    with pytest.raises(HTTPException) as error:
        ingest(("Submit " + character + "proof").encode("utf-8"))
    assert error.value.status_code == 422


def test_preserves_multilingual_text_and_layout():
    text = "提出書類\nمستندات مطلوبة\tProof of address"
    document = ingest(text.encode("utf-8"))
    assert document.text == text


def test_filename_cannot_smuggle_path_or_direction_override():
    document = ingest(b"Proof of address", filename="folder\\\\subdir/evil\u202e.txt")
    assert document.filename == "evil.txt"


def test_upload_hash_covers_original_bytes():
    import hashlib

    raw = b"  Proof of address  "
    document = ingest(raw)
    assert document.text == "Proof of address"
    assert document.sha256 == hashlib.sha256(raw).hexdigest()
