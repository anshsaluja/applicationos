from uuid import UUID

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

from .documents import ingest_upload
from .domain.evaluator import evaluate_requirements
from .domain.models import Requirement
from .persistence import DocumentRepository, build_session_factory, session_scope

router = APIRouter(prefix="/v1")


class EvaluateRequest(BaseModel):
    requirements: list[Requirement]


class EvaluateResponse(BaseModel):
    requirements: list[Requirement]
    missing_count: int
    inconsistent_count: int


class DocumentResponse(BaseModel):
    id: str
    filename: str
    sha256: str
    text: str


def get_session_factory():
    return build_session_factory()


@router.post("/requirements/evaluate", response_model=EvaluateResponse, tags=["requirements"])
def evaluate(payload: EvaluateRequest) -> EvaluateResponse:
    result = evaluate_requirements(payload.requirements)
    return EvaluateResponse(requirements=result.requirements, missing_count=result.missing_count, inconsistent_count=result.inconsistent_count)


@router.post("/documents", response_model=DocumentResponse, tags=["documents"])
async def upload_document(file: UploadFile) -> DocumentResponse:
    document = await ingest_upload(file)
    with session_scope(get_session_factory()) as session:
        row = DocumentRepository(session).add(document)
        return DocumentResponse(id=str(row.id), filename=row.filename, sha256=row.sha256, text=row.text)


@router.get("/documents/{document_id}", response_model=DocumentResponse, tags=["documents"])
def get_document(document_id: UUID) -> DocumentResponse:
    with session_scope(get_session_factory()) as session:
        row = DocumentRepository(session).get(document_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return DocumentResponse(id=str(row.id), filename=row.filename, sha256=row.sha256, text=row.text)
