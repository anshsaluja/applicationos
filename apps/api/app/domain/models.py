from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class RequirementStatus(StrEnum):
    PENDING = "pending"
    SATISFIED = "satisfied"
    MISSING = "missing"
    INCONSISTENT = "inconsistent"
    BLOCKED = "blocked"


class ApplicationWorkspace(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    application_type: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Evidence(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    source_document_id: UUID
    source_label: str
    excerpt: str
    page: int | None = None


class Requirement(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    title: str
    description: str
    status: RequirementStatus = RequirementStatus.PENDING
    deadline: datetime | None = None
    depends_on: list[UUID] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class ProposedAction(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    requirement_id: UUID | None = None
    action_type: str
    summary: str
    requires_approval: bool = True
    approved: bool = False
