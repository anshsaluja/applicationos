"""Regression tests for interrupted workflow recovery and retry policy.

These pure policy tests run without PostgreSQL; database-level recovery
remains subject to separate integration verification.
"""
from uuid import uuid4

import pytest

from app.domain.approvals import ApprovalDecision, ApprovalStatus
from app.domain.workflows import WorkflowState, WorkflowStatus, WorkflowTransitionError, transition


def approved(action_id):
    return ApprovalDecision(action_id=action_id, status=ApprovalStatus.APPROVED, reviewer_id="operator")


def test_retries_are_bounded_and_increment_only_when_running():
    action_id = uuid4()
    decision = approved(action_id)
    state = WorkflowState(action_id=action_id, idempotency_key="retry-test", max_attempts=2)
    state = transition(state, WorkflowStatus.AWAITING_APPROVAL)
    state = transition(state, WorkflowStatus.READY, approval=decision)
    assert state.attempt == 0
    state = transition(state, WorkflowStatus.RUNNING, approval=decision)
    assert state.attempt == 1
    state = transition(state, WorkflowStatus.FAILED)
    state = transition(state, WorkflowStatus.READY, approval=decision)
    state = transition(state, WorkflowStatus.RUNNING, approval=decision)
    assert state.attempt == 2
    state = transition(state, WorkflowStatus.FAILED)
    with pytest.raises(WorkflowTransitionError, match="Retry budget exhausted"):
        transition(state, WorkflowStatus.READY, approval=decision)


def test_failed_attempt_cannot_retry_without_approval():
    action_id = uuid4()
    decision = approved(action_id)
    state = WorkflowState(action_id=action_id, idempotency_key="gate")
    for target in (WorkflowStatus.AWAITING_APPROVAL, WorkflowStatus.READY, WorkflowStatus.RUNNING, WorkflowStatus.FAILED):
        state = transition(state, target, approval=decision)
    with pytest.raises(WorkflowTransitionError, match="Verified approval"):
        transition(state, WorkflowStatus.READY)


def test_completed_workflow_cannot_restart_or_reenter_review():
    action_id = uuid4()
    decision = approved(action_id)
    state = WorkflowState(action_id=action_id, idempotency_key="terminal")
    for target in (WorkflowStatus.AWAITING_APPROVAL, WorkflowStatus.READY, WorkflowStatus.RUNNING, WorkflowStatus.SUCCEEDED):
        state = transition(state, target, approval=decision)
    for target in (WorkflowStatus.READY, WorkflowStatus.RUNNING, WorkflowStatus.AWAITING_APPROVAL):
        with pytest.raises(WorkflowTransitionError, match="Invalid transition"):
            transition(state, target, approval=decision)


@pytest.mark.parametrize("attempt", [3, 4])
def test_exhausted_ready_checkpoint_cannot_be_replayed_or_dispatched(attempt):
    action_id = uuid4()
    state = WorkflowState(
        action_id=action_id,
        idempotency_key="exhausted-ready",
        status=WorkflowStatus.READY,
        attempt=attempt,
        max_attempts=3,
    )
    for target in (WorkflowStatus.READY, WorkflowStatus.RUNNING):
        with pytest.raises(WorkflowTransitionError, match="Retry budget exhausted|Invalid execution attempt"):
            transition(state, target, approval=approved(action_id))


def test_corrupt_checkpoint_cannot_be_replayed_into_success():
    action_id = uuid4()
    state = WorkflowState(
        action_id=action_id,
        idempotency_key="corrupt-running",
        status=WorkflowStatus.RUNNING,
        attempt=5,
        max_attempts=3,
    )
    with pytest.raises(WorkflowTransitionError, match="Invalid execution attempt"):
        transition(state, WorkflowStatus.SUCCEEDED)


def test_exhausted_review_checkpoint_cannot_become_ready():
    action_id = uuid4()
    state = WorkflowState(
        action_id=action_id,
        idempotency_key="corrupt-review",
        status=WorkflowStatus.AWAITING_APPROVAL,
        attempt=3,
        max_attempts=3,
    )
    with pytest.raises(WorkflowTransitionError, match="Retry budget exhausted"):
        transition(state, WorkflowStatus.READY, approval=approved(action_id))
