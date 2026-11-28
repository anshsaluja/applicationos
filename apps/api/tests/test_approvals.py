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


@pytest.mark.parametrize("reviewer_id", ["a" * 129, "x" * 10000])
def test_oversized_reviewer_identity_fails_closed_on_decision_and_replay(reviewer_id):
    action_id = uuid4()
    pending = ApprovalDecision(action_id=action_id)
    with pytest.raises(ApprovalGateError, match="valid reviewer identity"):
        decide(pending, ApprovalStatus.APPROVED, reviewer_id=reviewer_id)

    # A corrupted persisted approval must never authorize a consequential action.
    persisted = ApprovalDecision(
        action_id=action_id,
        status=ApprovalStatus.APPROVED,
        reviewer_id=reviewer_id,
    )
    with pytest.raises(ApprovalGateError, match="not been approved"):
        require_approved(persisted, action_id)


def test_maximum_length_reviewer_identity_remains_valid():
    reviewer_id = "a" * 128
    action_id = uuid4()
    approved = decide(ApprovalDecision(action_id=action_id), ApprovalStatus.APPROVED, reviewer_id=reviewer_id)
    require_approved(approved, action_id)


@pytest.mark.parametrize("reason", [None, "", "   ", "\n\t"])
def test_persisted_rejection_without_justification_cannot_be_replayed(reason):
    action_id = uuid4()
    corrupted = ApprovalDecision(
        action_id=action_id,
        status=ApprovalStatus.REJECTED,
        reviewer_id="reviewer-1",
        reason=reason,
    )
    with pytest.raises(ApprovalGateError, match="Persisted approval decision is invalid"):
        decide(corrupted, ApprovalStatus.REJECTED, reviewer_id="reviewer-1", reason=reason)
    with pytest.raises(ApprovalGateError, match="not been approved"):
        require_approved(corrupted, action_id)
