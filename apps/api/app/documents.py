from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile

MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_PDF_PAGES = 100
MAX_EXTRACTED_CHARACTERS = 1_000_000
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
    if media_type == "application/pdf" and not data.startswith(b"%PDF-"):
        raise HTTPException(status_code=422, detail="Invalid PDF signature")
    if media_type == "text/plain":
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=422, detail="Plain-text document must be valid UTF-8") from exc
    else:
        text = _extract_pdf(data)
    if len(text) > MAX_EXTRACTED_CHARACTERS:
        raise HTTPException(status_code=413, detail="Extracted document text exceeds limit")
    if not text.strip():
        raise HTTPException(status_code=422, detail="No extractable text found")
    return IngestedDocument(id=uuid4(), filename=_safe_filename(upload.filename), media_type=media_type, sha256=hashlib.sha256(data).hexdigest(), text=text.strip())


def _extract_pdf(data: bytes) -> str:
    try:
        import fitz
        with fitz.open(stream=data, filetype="pdf") as document:
            if document.needs_pass:
                raise HTTPException(status_code=422, detail="Password-protected PDFs are not supported")
            if len(document) > MAX_PDF_PAGES:
                raise HTTPException(status_code=413, detail="PDF exceeds 100-page limit")
            parts = []
            extracted_length = 0
            for page in document:
                page_text = page.get_text()
                extracted_length += len(page_text)
                if extracted_length > MAX_EXTRACTED_CHARACTERS:
                    raise HTTPException(status_code=413, detail="Extracted PDF text exceeds limit")
                parts.append(page_text)
            return "\n\n".join(parts)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Unable to parse PDF") from exc


def _safe_filename(filename: str | None) -> str:
    """Store a display-only basename, never a client-supplied path or control characters."""
    basename = (filename or "document").replace("\\", "/").split("/")[-1]
    basename = "".join(ch for ch in basename if ch.isprintable() and ch not in "/\\").strip()
    return basename[:240] or "document"
