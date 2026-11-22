"""Fail-closed approval policy for proposed external actions.

This module only makes decisions; it never executes an external action.
A durable audit trail and authenticated approver identity are required before
connecting this policy to any workflow executor.
"""
from __future__ import annotations

import unicodedata
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


def _valid_reviewer_id(value: str | None) -> bool:
    """Reject ambiguous identities even when loading persisted decisions."""
    return bool(
        value
        and len(value) <= 128
        and value == value.strip()
        and unicodedata.normalize("NFC", value) == value
        and not any(
            char.isspace() or unicodedata.category(char) in {"Cc", "Cf", "Cs", "Co", "Cn"}
            for char in value
        )
    )


def _valid_reason(value: str | None) -> bool:
    """Keep reviewer audit reasons bounded and safe to render in logs and UI."""
    return value is None or (
        len(value) <= 2000
        and not any(
            unicodedata.category(char) in {"Cc", "Cf", "Cs", "Co", "Cn"} and char not in ("\n", "\t")
            for char in value
        )
    )


def decide(
    current: ApprovalDecision,
    requested: ApprovalStatus,
    *,
    reviewer_id: str,
    reason: str | None = None,
) -> ApprovalDecision:
    """Allow a single terminal decision; repeated identical decisions are idempotent."""
    # Validate persisted terminal records before the incoming request. Otherwise
    # malformed replay input can mask corruption with an unrelated error.
    if current.status != ApprovalStatus.PENDING and (
        not _valid_reviewer_id(current.reviewer_id)
        or not _valid_reason(current.reason)
        or (current.reason is not None and current.reason != current.reason.strip())
        or (current.status == ApprovalStatus.REJECTED and not (current.reason or "").strip())
    ):
        raise ApprovalGateError("Persisted approval decision is invalid")
    if not _valid_reviewer_id(reviewer_id):
        raise ApprovalGateError("A valid reviewer identity is required")
    if not _valid_reason(reason):
        raise ApprovalGateError("Invalid approval reason")
    normalized_reason = (reason or "").strip() or None
    if requested == ApprovalStatus.PENDING:
        raise ApprovalGateError("Cannot transition back to pending")
    if requested == ApprovalStatus.REJECTED and not (reason or "").strip():
        raise ApprovalGateError("Rejection requires a reason")
    if current.status != ApprovalStatus.PENDING:
        if current.status == requested and current.reviewer_id == reviewer_id and (
            current.reason or None
        ) == normalized_reason:
            return current
        raise ApprovalGateError("Approval decision is final")
    return ApprovalDecision(
        action_id=current.action_id,
        status=requested,
        reviewer_id=reviewer_id,
        reason=normalized_reason,
    )


def require_approved(decision: ApprovalDecision | None, action_id: UUID) -> None:
    """Fail closed on missing, mismatched, pending, or rejected decisions."""
    if decision is None or decision.action_id != action_id:
        raise ApprovalGateError("No matching approval decision")
    if (
        decision.status != ApprovalStatus.APPROVED
        or not _valid_reviewer_id(decision.reviewer_id)
        or not _valid_reason(decision.reason)
        or (decision.reason is not None and decision.reason != decision.reason.strip())
    ):
        raise ApprovalGateError("Action has not been approved")
