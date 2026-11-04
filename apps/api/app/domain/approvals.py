"""Fail-closed approval policy for proposed external actions.

This module only makes decisions; it never executes an external action.
A durable audit trail and authenticated approver identity are required before
connecting this policy to any workflow executor.
"""
from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalDecision(BaseModel):
    action_id: UUID
    status: ApprovalStatus = ApprovalStatus.PENDING
    reviewer_id: str | None = None
    reason: str | None = None


class ApprovalGateError(ValueError):
    pass


def decide(
    current: ApprovalDecision,
    requested: ApprovalStatus,
    *,
    reviewer_id: str,
    reason: str | None = None,
) -> ApprovalDecision:
    """Allow a single terminal decision; repeated identical decisions are idempotent."""
    reviewer_id = reviewer_id.strip()
    if not reviewer_id:
        raise ApprovalGateError("A reviewer identity is required")
    if requested == ApprovalStatus.PENDING:
        raise ApprovalGateError("Cannot transition back to pending")
    if requested == ApprovalStatus.REJECTED and not (reason or "").strip():
        raise ApprovalGateError("Rejection requires a reason")
    if current.status != ApprovalStatus.PENDING:
        if current.status == requested and current.reviewer_id == reviewer_id and (
            current.reason or None
        ) == ((reason or "").strip() or None):
            return current
        raise ApprovalGateError("Approval decision is final")
    return ApprovalDecision(
        action_id=current.action_id,
        status=requested,
        reviewer_id=reviewer_id,
        reason=(reason or "").strip() or None,
    )


def require_approved(decision: ApprovalDecision | None, action_id: UUID) -> None:
    """Fail closed on missing, mismatched, pending, or rejected decisions."""
    if decision is None or decision.action_id != action_id:
        raise ApprovalGateError("No matching approval decision")
    if decision.status != ApprovalStatus.APPROVED or not decision.reviewer_id:
        raise ApprovalGateError("Action has not been approved")
