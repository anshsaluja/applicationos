from fastapi import APIRouter, UploadFile
from pydantic import BaseModel

from .documents import ingest_upload
from .domain.evaluator import evaluate_requirements
from .domain.models import Requirement

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


@router.post("/requirements/evaluate", response_model=EvaluateResponse, tags=["requirements"])
def evaluate(payload: EvaluateRequest) -> EvaluateResponse:
    result = evaluate_requirements(payload.requirements)
    return EvaluateResponse(requirements=result.requirements, missing_count=result.missing_count, inconsistent_count=result.inconsistent_count)


@router.post("/documents", response_model=DocumentResponse, tags=["documents"])
async def upload_document(file: UploadFile) -> DocumentResponse:
    document = await ingest_upload(file)
    return DocumentResponse(id=str(document.id), filename=document.filename, sha256=document.sha256, text=document.text)
