"""Regression coverage for fail-closed workflow state and retry policy."""

from uuid import uuid4

import pytest

from app.domain.approvals import ApprovalDecision, ApprovalStatus
from app.domain.workflows import (
    WorkflowState,
    WorkflowStatus,
    WorkflowTransitionError,
    transition,
)


def make_state(*, max_attempts: int = 2) -> WorkflowState:
    return WorkflowState(
        action_id=uuid4(),
        idempotency_key=str(uuid4()),
        max_attempts=max_attempts,
    )


def approval_for(state: WorkflowState) -> ApprovalDecision:
    return ApprovalDecision(
        action_id=state.action_id,
        status=ApprovalStatus.APPROVED,
        reviewer_id="local-test-reviewer",
    )


@pytest.mark.parametrize("status", [ApprovalStatus.PENDING, ApprovalStatus.REJECTED])
def test_unapproved_workflow_cannot_become_ready(status: ApprovalStatus) -> None:
    state = transition(make_state(), WorkflowStatus.AWAITING_APPROVAL)
    decision = ApprovalDecision(action_id=state.action_id, status=status, reviewer_id="reviewer")
    with pytest.raises(WorkflowTransitionError, match="Verified approval"):
        transition(state, WorkflowStatus.READY, approval=decision)


def test_mismatched_approval_cannot_authorize_workflow() -> None:
    state = transition(make_state(), WorkflowStatus.AWAITING_APPROVAL)
    unrelated = ApprovalDecision(
        action_id=uuid4(), status=ApprovalStatus.APPROVED, reviewer_id="reviewer"
    )
    with pytest.raises(WorkflowTransitionError, match="Verified approval"):
        transition(state, WorkflowStatus.READY, approval=unrelated)


def test_execution_rechecks_approval_even_after_ready() -> None:
    state = transition(make_state(), WorkflowStatus.AWAITING_APPROVAL)
    state = transition(state, WorkflowStatus.READY, approval=approval_for(state))
    with pytest.raises(WorkflowTransitionError, match="Verified approval"):
        transition(state, WorkflowStatus.RUNNING)
    assert state.attempt == 0


def test_retry_budget_is_consumed_only_when_execution_starts() -> None:
    state = transition(make_state(), WorkflowStatus.AWAITING_APPROVAL)
    approved = approval_for(state)
    state = transition(state, WorkflowStatus.READY, approval=approved)
    assert state.attempt == 0

    state = transition(state, WorkflowStatus.RUNNING, approval=approved)
    assert state.attempt == 1
    state = transition(state, WorkflowStatus.FAILED)
    state = transition(state, WorkflowStatus.READY, approval=approved)
    assert state.attempt == 1

    state = transition(state, WorkflowStatus.RUNNING, approval=approved)
    assert state.attempt == 2
    state = transition(state, WorkflowStatus.FAILED)
    with pytest.raises(WorkflowTransitionError, match="Retry budget exhausted"):
        transition(state, WorkflowStatus.READY, approval=approved)


def test_success_is_terminal_and_duplicate_transition_is_safe() -> None:
    state = transition(make_state(), WorkflowStatus.AWAITING_APPROVAL)
    approved = approval_for(state)
    state = transition(state, WorkflowStatus.READY, approval=approved)
    state = transition(state, WorkflowStatus.RUNNING, approval=approved)
    state = transition(state, WorkflowStatus.SUCCEEDED)
    assert transition(state, WorkflowStatus.SUCCEEDED) == state
    with pytest.raises(WorkflowTransitionError, match="Invalid transition"):
        transition(state, WorkflowStatus.READY, approval=approved)


def test_rejected_workflow_cannot_reenter_review() -> None:
    state = transition(make_state(), WorkflowStatus.AWAITING_APPROVAL)
    state = transition(state, WorkflowStatus.FAILED)
    with pytest.raises(WorkflowTransitionError, match="Invalid transition"):
        transition(state, WorkflowStatus.AWAITING_APPROVAL)
