from uuid import UUID

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

from .documents import ingest_upload
from .domain.evaluator import evaluate_requirements
from .domain.models import Requirement
from .extraction import extract_requirements
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


@router.get("/documents/{document_id}/requirements", response_model=list[Requirement], tags=["requirements"])
def document_requirement_candidates(document_id: UUID) -> list[Requirement]:
    """Extract review candidates from stored instructions, not proof of satisfaction."""
    with session_scope(get_session_factory()) as session:
        row = DocumentRepository(session).get(document_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return extract_requirements(row.id, row.filename, row.text)


class RequirementSourceResponse(BaseModel):
    requirement_id: str
    instruction_excerpt: str
    source_document_id: str
    source_label: str
    status: str
    satisfaction_evidence: list[str]


@router.get("/documents/{document_id}/requirement-sources", response_model=list[RequirementSourceResponse], tags=["requirements"])
def document_requirement_sources(document_id: UUID) -> list[RequirementSourceResponse]:
    """Expose instruction provenance separately from compliance evidence."""
    with session_scope(get_session_factory()) as session:
        row = DocumentRepository(session).get(document_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return [
            RequirementSourceResponse(
                requirement_id=str(requirement.id),
                instruction_excerpt=requirement.description,
                source_document_id=str(row.id),
                source_label=row.filename,
                status=requirement.status.value,
                satisfaction_evidence=[],
            )
            for requirement in extract_requirements(row.id, row.filename, row.text)
        ]


class PersistedRequirementsResponse(BaseModel):
    workspace_id: str
    requirements: list[Requirement]


@router.post("/documents/{document_id}/requirements/persist", response_model=PersistedRequirementsResponse, tags=["requirements"])
def persist_document_requirements(document_id: UUID) -> PersistedRequirementsResponse:
    """Persist pending review candidates idempotently; never mark them satisfied."""
    from uuid import uuid5

    from .domain.models import ApplicationWorkspace
    from .persistence import WorkspaceRepository, WorkspaceRow

    with session_scope(get_session_factory()) as session:
        document = DocumentRepository(session).get(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        workspace_id = uuid5(document_id, "applicationos:requirements-workspace")
        repository = WorkspaceRepository(session)
        if session.get(WorkspaceRow, workspace_id) is None:
            repository.create(ApplicationWorkspace(id=workspace_id, name=document.filename, application_type="document-review"))
        existing = {item.id for item in repository.list_requirements(workspace_id)}
        for candidate in extract_requirements(document.id, document.filename, document.text):
            if candidate.id not in existing:
                repository.add_requirement(workspace_id, candidate)
        return PersistedRequirementsResponse(workspace_id=str(workspace_id), requirements=repository.list_requirements(workspace_id))
