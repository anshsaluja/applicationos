from uuid import uuid4

import pytest

from app.domain.approvals import (
    ApprovalDecision,
    ApprovalGateError,
    ApprovalStatus,
    decide,
    require_approved,
)


def test_pending_and_missing_approvals_fail_closed():
    action_id = uuid4()
    for decision in (None, ApprovalDecision(action_id=action_id)):
        with pytest.raises(ApprovalGateError):
            require_approved(decision, action_id)


def test_approval_requires_reviewer_and_is_idempotent():
    initial = ApprovalDecision(action_id=uuid4())
    with pytest.raises(ApprovalGateError):
        decide(initial, ApprovalStatus.APPROVED, reviewer_id=" ")
    approved = decide(initial, ApprovalStatus.APPROVED, reviewer_id="reviewer-1")
    assert decide(approved, ApprovalStatus.APPROVED, reviewer_id="reviewer-1") == approved
    require_approved(approved, initial.action_id)
    with pytest.raises(ApprovalGateError):
        require_approved(approved, uuid4())


def test_rejection_requires_reason_and_cannot_be_overridden():
    initial = ApprovalDecision(action_id=uuid4())
    with pytest.raises(ApprovalGateError):
        decide(initial, ApprovalStatus.REJECTED, reviewer_id="reviewer-1")
    rejected = decide(initial, ApprovalStatus.REJECTED, reviewer_id="reviewer-1", reason="Unsafe")
    with pytest.raises(ApprovalGateError):
        require_approved(rejected, initial.action_id)
    with pytest.raises(ApprovalGateError):
        decide(rejected, ApprovalStatus.APPROVED, reviewer_id="reviewer-1")


def test_approved_decision_cannot_be_changed_or_reset():
    initial = ApprovalDecision(action_id=uuid4())
    approved = decide(initial, ApprovalStatus.APPROVED, reviewer_id="reviewer-1")
    for status in (ApprovalStatus.REJECTED, ApprovalStatus.PENDING):
        with pytest.raises(ApprovalGateError):
            decide(approved, status, reviewer_id="reviewer-2", reason="changed")
