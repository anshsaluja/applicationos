"""Regression tests for deceptive Unicode formatting in uploaded evidence."""

from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.documents import ingest_upload


@pytest.mark.asyncio
@pytest.mark.parametrize("control", ["\u202e", "\u202d", "\u2066", "\u2069"])
async def test_rejects_bidirectional_controls(control: str) -> None:
    upload = UploadFile(filename="requirements.txt", headers=Headers({"content-type": "text/plain"}), file=BytesIO(("Submit evidence " + control + "now").encode("utf-8")))
    with pytest.raises(HTTPException) as error:
        await ingest_upload(upload)
    assert error.value.status_code == 422
    assert "bidirectional" in error.value.detail


@pytest.mark.asyncio
async def test_accepts_normal_multilingual_text() -> None:
    upload = UploadFile(filename="requirements.txt", headers=Headers({"content-type": "text/plain"}), file=BytesIO("Résumé: 提交材料".encode("utf-8")))
    document = await ingest_upload(upload)
    assert document.text == "Résumé: 提交材料"
