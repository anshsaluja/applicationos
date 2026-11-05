from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, create_engine
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .domain.models import ApplicationWorkspace, Evidence, Requirement, RequirementStatus

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://applicationos:applicationos@localhost:5432/applicationos")


class Base(DeclarativeBase):
    pass


class WorkspaceRow(Base):
    __tablename__ = "workspaces"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    application_type: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    requirements: Mapped[list[RequirementRow]] = relationship(cascade="all, delete-orphan")


class RequirementRow(Base):
    __tablename__ = "requirements"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default=RequirementStatus.PENDING.value)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence: Mapped[list[EvidenceRow]] = relationship(cascade="all, delete-orphan")


class EvidenceRow(Base):
    __tablename__ = "evidence"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    requirement_id: Mapped[UUID] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), index=True)
    source_document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    source_label: Mapped[str] = mapped_column(String(240))
    excerpt: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(nullable=True)


class DocumentRow(Base):
    __tablename__ = "documents"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    filename: Mapped[str] = mapped_column(String(240))
    media_type: Mapped[str] = mapped_column(String(120))
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def build_engine(url: str | None = None):
    return create_engine(url or DATABASE_URL, pool_pre_ping=True)


def build_session_factory(url: str | None = None):
    return sessionmaker(bind=build_engine(url), expire_on_commit=False)


@contextmanager
def session_scope(factory):
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class DocumentRepository:
    def __init__(self, session):
        self.session = session

    def add(self, document) -> DocumentRow:
        existing = self.session.query(DocumentRow).filter_by(sha256=document.sha256).one_or_none()
        if existing is not None:
            return existing
        row = DocumentRow(
            id=document.id,
            filename=document.filename,
            media_type=document.media_type,
            sha256=document.sha256,
            text=document.text,
            created_at=datetime.now(UTC),
        )
        self.session.add(row)
        self.session.flush()
        return row


    def get(self, document_id: UUID) -> DocumentRow | None:
        return self.session.get(DocumentRow, document_id)


class WorkspaceRepository:
    def __init__(self, session):
        self.session = session

    def create(self, workspace: ApplicationWorkspace) -> ApplicationWorkspace:
        self.session.add(WorkspaceRow(id=workspace.id, name=workspace.name, application_type=workspace.application_type, created_at=workspace.created_at))
        self.session.flush()
        return workspace

    def add_requirement(self, workspace_id: UUID, requirement: Requirement) -> Requirement:
        row = RequirementRow(id=requirement.id, workspace_id=workspace_id, title=requirement.title, description=requirement.description, status=requirement.status.value, deadline=requirement.deadline)
        row.evidence = [EvidenceRow(id=e.id, source_document_id=e.source_document_id, source_label=e.source_label, excerpt=e.excerpt, page=e.page) for e in requirement.evidence]
        self.session.add(row)
        self.session.flush()
        return requirement

    def list_requirements(self, workspace_id: UUID) -> list[Requirement]:
        rows = self.session.query(RequirementRow).filter_by(workspace_id=workspace_id).all()
        return [Requirement(id=r.id, title=r.title, description=r.description, status=RequirementStatus(r.status), deadline=r.deadline, evidence=[Evidence(id=e.id, source_document_id=e.source_document_id, source_label=e.source_label, excerpt=e.excerpt, page=e.page) for e in r.evidence]) for r in rows]


class ApprovalRow(Base):
    """Immutable terminal decision, keyed by the proposed action."""
    __tablename__ = "approval_decisions"
    action_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reviewer_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApprovalRepository:
    """Persist a single terminal decision; concurrent conflicting writers fail closed.

    Call within session_scope. Never treat a supplied reviewer_id as authenticated.
    """
    def __init__(self, session):
        self.session = session

    def get(self, action_id: UUID):
        from .domain.approvals import ApprovalDecision, ApprovalStatus

        row = self.session.get(ApprovalRow, action_id)
        if row is None:
            return ApprovalDecision(action_id=action_id)
        return ApprovalDecision(
            action_id=row.action_id,
            status=ApprovalStatus(row.status),
            reviewer_id=row.reviewer_id,
            reason=row.reason,
        )

    def decide(self, action_id: UUID, requested, *, reviewer_id: str, reason: str | None = None):
        # Serialize decisions for the same action, including when no row exists yet.
        # A transaction-scoped advisory lock prevents two first-time writers racing.
        from sqlalchemy import text

        from .domain.approvals import ApprovalStatus, decide

        lock_key = int.from_bytes(action_id.bytes[:8], "big", signed=True)
        self.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
        current = self.get(action_id)
        updated = decide(current, ApprovalStatus(requested), reviewer_id=reviewer_id, reason=reason)
        if current.status == ApprovalStatus.PENDING:
            self.session.add(
                ApprovalRow(
                    action_id=action_id,
                    status=updated.status.value,
                    reviewer_id=updated.reviewer_id,
                    reason=updated.reason,
                    decided_at=datetime.now(UTC),
                )
            )
            self.session.flush()
        return updated


class WorkflowRow(Base):
    """Durable workflow checkpoint; the idempotency key is globally unique."""
    __tablename__ = "workflow_checkpoints"
    action_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt: Mapped[int] = mapped_column(nullable=False)
    max_attempts: Mapped[int] = mapped_column(nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class WorkflowRepository:
    """Atomic, locked workflow transitions with approval rechecks.

    No external side effects are dispatched here. A durable outbox/worker is
    required before executing any approved action.
    """

    def __init__(self, session):
        self.session = session

    @staticmethod
    def _state(row):
        from .domain.workflows import WorkflowState

        return WorkflowState(
            action_id=row.action_id,
            idempotency_key=row.idempotency_key,
            status=row.status,
            attempt=row.attempt,
            max_attempts=row.max_attempts,
            last_error=row.last_error,
        )

    def create(self, state):
        from sqlalchemy.exc import IntegrityError

        from .domain.workflows import WorkflowStatus, WorkflowTransitionError

        if state.status != WorkflowStatus.PENDING or state.attempt != 0:
            raise WorkflowTransitionError("Only a fresh pending workflow may be created")
        # Lock the action identifier before checking uniqueness.
        from sqlalchemy import text

        lock_key = int.from_bytes(state.action_id.bytes[:8], "big", signed=True)
        self.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
        existing = self.session.get(WorkflowRow, state.action_id)
        if existing is not None:
            if existing.idempotency_key != state.idempotency_key:
                raise WorkflowTransitionError("Action already has a different idempotency key")
            return self._state(existing)
        row = WorkflowRow(
            action_id=state.action_id,
            idempotency_key=state.idempotency_key,
            status=state.status.value,
            attempt=state.attempt,
            max_attempts=state.max_attempts,
            last_error=state.last_error,
        )
        try:
            with self.session.begin_nested():
                self.session.add(row)
                self.session.flush()
        except IntegrityError as exc:
            raise WorkflowTransitionError("Idempotency key already belongs to another action") from exc
        return self._state(row)

    def get(self, action_id: UUID):
        row = self.session.get(WorkflowRow, action_id)
        return None if row is None else self._state(row)

    def advance(self, action_id: UUID, target, *, error: str | None = None):
        from .domain.workflows import WorkflowStatus, WorkflowTransitionError, transition

        row = (
            self.session.query(WorkflowRow)
            .filter_by(action_id=action_id)
            .with_for_update()
            .one_or_none()
        )
        if row is None:
            raise WorkflowTransitionError("Workflow not found")
        current = self._state(row)
        # Recheck the durable approval under the transaction, never trust
        # a caller-supplied approval object.
        approval = ApprovalRepository(self.session).get(action_id)
        updated = transition(current, WorkflowStatus(target), approval=approval)
        if target == WorkflowStatus.FAILED and error is not None:
            updated = updated.model_copy(update={"last_error": error[:2000]})
        row.status = updated.status.value
        row.attempt = updated.attempt
        row.last_error = updated.last_error
        self.session.flush()
        return updated

    def recover_interrupted(self, action_id: UUID, *, reason: str = "Worker interrupted"):
        """Mark an interrupted RUNNING attempt as failed without replaying effects.

        Call only after the owning worker is known to have stopped. This method
        deliberately does not redispatch work: a future outbox/worker must
        reconcile potentially completed external side effects first.
        """
        from .domain.workflows import WorkflowStatus, WorkflowTransitionError, transition

        if not reason.strip():
            raise WorkflowTransitionError("Recovery reason must not be empty")
        row = (
            self.session.query(WorkflowRow)
            .filter_by(action_id=action_id)
            .with_for_update()
            .one_or_none()
        )
        if row is None:
            raise WorkflowTransitionError("Workflow not found")
        current = self._state(row)
        if current.status == WorkflowStatus.FAILED:
            return current  # Repeated recovery requests must not consume retries.
        if current.status != WorkflowStatus.RUNNING:
            raise WorkflowTransitionError("Only running workflows can be recovered")
        updated = transition(current, WorkflowStatus.FAILED)
        row.status = updated.status.value
        row.last_error = reason[:2000]
        self.session.flush()
        return self._state(row)
