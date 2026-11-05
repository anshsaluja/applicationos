"""Regression coverage for fail-closed approval and workflow boundaries.

These tests are pure domain tests; they do not replace PostgreSQL integration
or browser end-to-end verification.
"""
from uuid import uuid4

import pytest

from app.domain.approvals import (
    ApprovalDecision,
    ApprovalGateError,
    ApprovalStatus,
    decide,
    require_approved,
)
from app.domain.workflows import (
    WorkflowState,
    WorkflowStatus,
    WorkflowTransitionError,
    transition,
)


def test_approval_requires_real_reviewer_and_rejection_reason():
    pending = ApprovalDecision(action_id=uuid4())
    with pytest.raises(ApprovalGateError, match="reviewer"):
        decide(pending, ApprovalStatus.APPROVED, reviewer_id="  ")
    with pytest.raises(ApprovalGateError, match="reason"):
        decide(pending, ApprovalStatus.REJECTED, reviewer_id="reviewer", reason="  ")
    with pytest.raises(ApprovalGateError, match="pending"):
        decide(pending, ApprovalStatus.PENDING, reviewer_id="reviewer")


def test_terminal_approval_is_idempotent_but_cannot_be_overridden():
    pending = ApprovalDecision(action_id=uuid4())
    approved = decide(pending, ApprovalStatus.APPROVED, reviewer_id="reviewer")
    assert decide(approved, ApprovalStatus.APPROVED, reviewer_id="reviewer") == approved
    with pytest.raises(ApprovalGateError, match="final"):
        decide(approved, ApprovalStatus.REJECTED, reviewer_id="reviewer", reason="changed")
    with pytest.raises(ApprovalGateError, match="final"):
        decide(approved, ApprovalStatus.APPROVED, reviewer_id="another")


def test_approval_for_other_action_never_authorizes_workflow():
    action_id = uuid4()
    unrelated = ApprovalDecision(
        action_id=uuid4(), status=ApprovalStatus.APPROVED, reviewer_id="reviewer"
    )
    with pytest.raises(ApprovalGateError, match="matching"):
        require_approved(unrelated, action_id)
    with pytest.raises(ApprovalGateError, match="matching"):
        require_approved(None, action_id)
    with pytest.raises(ApprovalGateError, match="approved"):
        require_approved(ApprovalDecision(action_id=action_id), action_id)


def test_rejected_approval_cannot_start_workflow():
    action_id = uuid4()
    state = WorkflowState(action_id=action_id, idempotency_key="reject-case")
    waiting = transition(state, WorkflowStatus.AWAITING_APPROVAL)
    rejected = ApprovalDecision(
        action_id=action_id, status=ApprovalStatus.REJECTED,
        reviewer_id="reviewer", reason="Insufficient evidence"
    )
    with pytest.raises(WorkflowTransitionError, match="approval"):
        transition(waiting, WorkflowStatus.READY, approval=rejected)
    assert waiting.status == WorkflowStatus.AWAITING_APPROVAL
    assert waiting.attempt == 0


def test_retry_never_increments_attempt_until_running():
    action_id = uuid4()
    approval = ApprovalDecision(
        action_id=action_id, status=ApprovalStatus.APPROVED, reviewer_id="reviewer"
    )
    state = WorkflowState(
        action_id=action_id, idempotency_key="retry-case", max_attempts=2
    )
    waiting = transition(state, WorkflowStatus.AWAITING_APPROVAL)
    ready = transition(waiting, WorkflowStatus.READY, approval=approval)
    assert ready.attempt == 0
    running = transition(ready, WorkflowStatus.RUNNING, approval=approval)
    assert running.attempt == 1
    failed = transition(running, WorkflowStatus.FAILED)
    retry_ready = transition(failed, WorkflowStatus.READY, approval=approval)
    assert retry_ready.attempt == 1
    second_running = transition(
        retry_ready, WorkflowStatus.RUNNING, approval=approval
    )
    assert second_running.attempt == 2
    exhausted = transition(second_running, WorkflowStatus.FAILED)
    with pytest.raises(WorkflowTransitionError, match="budget"):
        transition(exhausted, WorkflowStatus.READY, approval=approval)
