from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile

MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
ALLOWED_TYPES = {"application/pdf", "text/plain"}


@dataclass(frozen=True)
class IngestedDocument:
    id: UUID
    filename: str
    media_type: str
    sha256: str
    text: str


async def ingest_upload(upload: UploadFile) -> IngestedDocument:
    media_type = upload.content_type or "application/octet-stream"
    if media_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="Only PDF and plain-text documents are supported")
    data = await upload.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="Document exceeds 8 MiB limit")
    if not data:
        raise HTTPException(status_code=422, detail="Document is empty")
    if media_type == "text/plain":
        text = data.decode("utf-8", errors="strict")
    else:
        text = _extract_pdf(data)
    if not text.strip():
        raise HTTPException(status_code=422, detail="No extractable text found")
    return IngestedDocument(id=uuid4(), filename=upload.filename or "document", media_type=media_type, sha256=hashlib.sha256(data).hexdigest(), text=text.strip())


def _extract_pdf(data: bytes) -> str:
    try:
        import fitz
        with fitz.open(stream=data, filetype="pdf") as document:
            return "\n\n".join(page.get_text() for page in document)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Unable to parse PDF") from exc
