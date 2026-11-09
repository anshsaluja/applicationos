from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

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
        # Serialize concurrent persistence requests for the same document.
        # Otherwise both callers may insert the same deterministic UUID.
        from sqlalchemy import text

        lock_key = int.from_bytes(document_id.bytes[:8], "big", signed=True)
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
        document = DocumentRepository(session).get(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        workspace_id = uuid5(document_id, "applicationos:requirements-workspace")
        repository = WorkspaceRepository(session)
        if session.get(WorkspaceRow, workspace_id) is None:
            repository.create(
                ApplicationWorkspace(
                    id=workspace_id, name=document.filename, application_type="document-review"
                )
            )
        existing = {item.id for item in repository.list_requirements(workspace_id)}
        for candidate in extract_requirements(document.id, document.filename, document.text):
            if candidate.id not in existing:
                repository.add_requirement(workspace_id, candidate)
        return PersistedRequirementsResponse(
            workspace_id=str(workspace_id), requirements=repository.list_requirements(workspace_id)
        )


@router.get("/workspaces/{workspace_id}/requirements", response_model=PersistedRequirementsResponse, tags=["requirements"])
def get_persisted_workspace_requirements(workspace_id: UUID) -> PersistedRequirementsResponse:
    """Read stored requirement state without re-extracting or mutating it."""
    from .persistence import WorkspaceRepository, WorkspaceRow

    with session_scope(get_session_factory()) as session:
        if session.get(WorkspaceRow, workspace_id) is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return PersistedRequirementsResponse(
            workspace_id=str(workspace_id),
            requirements=WorkspaceRepository(session).list_requirements(workspace_id),
        )


class WorkflowCheckpointResponse(BaseModel):
    action_id: UUID
    idempotency_key: str
    status: str
    attempt: int
    max_attempts: int
    last_error: str | None


@router.get("/workflows", response_model=list[WorkflowCheckpointResponse], tags=["workflows"])
def list_workflow_checkpoints(limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0, le=10000)) -> list[WorkflowCheckpointResponse]:
    """Bounded read-only checkpoint inspection for local development.

    This endpoint is not tenant-isolated; require authentication before hosting.
    """
    from .persistence import WorkflowRepository

    with session_scope(get_session_factory()) as session:
        return [
            WorkflowCheckpointResponse(**state.model_dump())
            for state in WorkflowRepository(session).list_recent(limit=limit, offset=offset)
        ]


@router.get("/workflows/{action_id}", response_model=WorkflowCheckpointResponse, tags=["workflows"])
def get_workflow_checkpoint(action_id: UUID) -> WorkflowCheckpointResponse:
    """Read durable workflow progress; this endpoint cannot execute actions."""
    from .persistence import WorkflowRepository

    with session_scope(get_session_factory()) as session:
        state = WorkflowRepository(session).get(action_id)
        if state is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return WorkflowCheckpointResponse(**state.model_dump())


class WorkflowCreateRequest(BaseModel):
    action_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=200)
    max_attempts: int = Field(default=3, ge=1, le=10)


@router.post("/workflows", response_model=WorkflowCheckpointResponse, tags=["workflows"])
def create_workflow_checkpoint(payload: WorkflowCreateRequest) -> WorkflowCheckpointResponse:
    """Record pending intent only. Never approve or dispatch external actions."""
    from fastapi import HTTPException

    from .domain.workflows import WorkflowState, WorkflowTransitionError
    from .persistence import WorkflowRepository

    try:
        state = WorkflowState(
            action_id=payload.action_id,
            idempotency_key=payload.idempotency_key,
            max_attempts=payload.max_attempts,
        )
        with session_scope(get_session_factory()) as session:
            saved = WorkflowRepository(session).create(state)
            return WorkflowCheckpointResponse(**saved.model_dump())
    except WorkflowTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/workflows/{action_id}/request-review", response_model=WorkflowCheckpointResponse, tags=["workflows"])
def request_workflow_review(action_id: UUID) -> WorkflowCheckpointResponse:
    """Move a pending workflow into review; never approve or execute it.

    Duplicate requests are idempotent. All other states fail closed so that
    callers cannot use this endpoint to reset a decision or retry budget.
    """
    from .domain.workflows import WorkflowStatus, WorkflowTransitionError
    from .persistence import WorkflowRepository

    try:
        with session_scope(get_session_factory()) as session:
            repository = WorkflowRepository(session)
            state = repository.get(action_id)
            if state is None:
                raise HTTPException(status_code=404, detail="Workflow not found")
            if state.status not in {WorkflowStatus.PENDING, WorkflowStatus.AWAITING_APPROVAL}:
                raise HTTPException(status_code=409, detail="Workflow is no longer eligible for review")
            updated = repository.advance(action_id, WorkflowStatus.AWAITING_APPROVAL)
            return WorkflowCheckpointResponse(**updated.model_dump())
    except WorkflowTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class WorkflowDecisionRequest(BaseModel):
    decision: str
    reason: str | None = Field(default=None, max_length=2000)


@router.post("/workflows/{action_id}/decision", response_model=WorkflowCheckpointResponse, tags=["workflows"])
def decide_workflow_review(
    action_id: UUID,
    payload: WorkflowDecisionRequest,
    x_review_token: str | None = __import__("fastapi").Header(default=None),
) -> WorkflowCheckpointResponse:
    """Local operator approval gate. Disabled unless explicit credentials are configured.

    This is intentionally a single-operator boundary, not multi-user authentication.
    Never expose it publicly without proper identity, RBAC, and audit logging.
    """
    import hmac
    import os

    from .domain.approvals import ApprovalGateError, ApprovalStatus
    from .domain.workflows import WorkflowStatus, WorkflowTransitionError
    from .persistence import ApprovalRepository, WorkflowRepository

    expected = os.getenv("APPLICATIONOS_REVIEW_TOKEN", "")
    reviewer = os.getenv("APPLICATIONOS_REVIEWER_ID", "").strip()
    if not expected or not reviewer or not x_review_token or not hmac.compare_digest(x_review_token, expected):
        raise HTTPException(status_code=403, detail="Review authorization unavailable or denied")
    if payload.decision not in {"approved", "rejected"}:
        raise HTTPException(status_code=422, detail="Decision must be approved or rejected")
    try:
        with session_scope(get_session_factory()) as session:
            workflow = WorkflowRepository(session)
            state = workflow.get(action_id)
            if state is None:
                raise HTTPException(status_code=404, detail="Workflow not found")
            if state.status != WorkflowStatus.AWAITING_APPROVAL:
                raise HTTPException(status_code=409, detail="Workflow is not awaiting approval")
            ApprovalRepository(session).decide(
                action_id, ApprovalStatus(payload.decision),
                reviewer_id=reviewer, reason=payload.reason,
            )
            target = WorkflowStatus.READY if payload.decision == "approved" else WorkflowStatus.FAILED
            updated = workflow.advance(action_id, target)
            return WorkflowCheckpointResponse(**updated.model_dump())
    except (ApprovalGateError, WorkflowTransitionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
