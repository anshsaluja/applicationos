"""Regression tests for fail-closed workflow dispatch and recovery transitions.

These pure-domain tests do not imply a durable worker or external action executor.
"""
from uuid import uuid4

import pytest

from app.domain.approvals import ApprovalDecision, ApprovalStatus
from app.domain.workflows import (
    WorkflowState,
    WorkflowStatus,
    WorkflowTransitionError,
    require_dispatch_authorization,
    transition,
)


def test_dispatch_requires_matching_durable_approval():
    action_id = uuid4()
    state = WorkflowState(
        action_id=action_id, idempotency_key="dispatch-guard",
        status=WorkflowStatus.RUNNING, attempt=1,
    )
    with pytest.raises(WorkflowTransitionError, match="Verified approval"):
        require_dispatch_authorization(state)
    with pytest.raises(WorkflowTransitionError, match="Verified approval"):
        require_dispatch_authorization(
            state,
            approval=ApprovalDecision(
                action_id=uuid4(), status=ApprovalStatus.APPROVED, reviewer_id="operator"
            ),
        )
    require_dispatch_authorization(
        state,
        approval=ApprovalDecision(
            action_id=action_id, status=ApprovalStatus.APPROVED, reviewer_id="operator"
        ),
    )


@pytest.mark.parametrize("attempt", [0, 4])
def test_dispatch_rejects_invalid_attempts(attempt):
    action_id = uuid4()
    state = WorkflowState(
        action_id=action_id, idempotency_key="attempt-guard",
        status=WorkflowStatus.RUNNING, attempt=attempt, max_attempts=3,
    )
    with pytest.raises(WorkflowTransitionError, match="Invalid execution attempt"):
        require_dispatch_authorization(
            state,
            approval=ApprovalDecision(
                action_id=action_id, status=ApprovalStatus.APPROVED, reviewer_id="operator"
            ),
        )


def test_interrupted_attempt_requires_explicit_reapproval_check_before_retry():
    action_id = uuid4()
    approved = ApprovalDecision(
        action_id=action_id, status=ApprovalStatus.APPROVED, reviewer_id="operator"
    )
    state = WorkflowState(
        action_id=action_id, idempotency_key="recovery", status=WorkflowStatus.RUNNING,
        attempt=1, max_attempts=2,
    )
    failed = transition(state, WorkflowStatus.FAILED)
    with pytest.raises(WorkflowTransitionError, match="Verified approval"):
        transition(failed, WorkflowStatus.READY)
    ready = transition(failed, WorkflowStatus.READY, approval=approved)
    running = transition(ready, WorkflowStatus.RUNNING, approval=approved)
    assert running.attempt == 2
    exhausted = transition(running, WorkflowStatus.FAILED)
    with pytest.raises(WorkflowTransitionError, match="Retry budget exhausted"):
        transition(exhausted, WorkflowStatus.READY, approval=approved)
