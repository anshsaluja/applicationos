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
        from .domain.approvals import ApprovalGateError, ApprovalStatus, decide

        # Serialize decisions for the same action, including when no row exists yet.
        # A transaction-scoped advisory lock prevents two first-time writers racing.
        from sqlalchemy import text

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
