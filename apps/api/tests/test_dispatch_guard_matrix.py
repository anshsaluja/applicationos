"""Fail-closed dispatch authorization matrix for recovered workflow checkpoints.

These tests exercise the domain boundary independently of database claims.
They do not establish exactly-once delivery; PostgreSQL integration tests must
also cover concurrent claims and crash recovery.
"""

from uuid import uuid4

import pytest

from app.domain.approvals import ApprovalDecision, ApprovalStatus
from app.domain.workflows import (
    WorkflowState,
    WorkflowStatus,
    WorkflowTransitionError,
    require_dispatch_authorization,
)


def _running_state() -> WorkflowState:
    return WorkflowState(
        action_id=uuid4(),
        status=WorkflowStatus.RUNNING,
        attempt=1,
        max_attempts=3,
        idempotency_key=str(uuid4()),
    )


def _approval(state: WorkflowState, status: ApprovalStatus = ApprovalStatus.APPROVED):
    return ApprovalDecision(
        action_id=state.action_id,
        status=status,
        reviewer_id="synthetic-test-reviewer",
    )


def test_valid_running_checkpoint_with_matching_approval_can_dispatch() -> None:
    state = _running_state()
    assert require_dispatch_authorization(state, approval=_approval(state)) is None


@pytest.mark.parametrize(
    "status",
    [WorkflowStatus.PENDING, WorkflowStatus.AWAITING_APPROVAL,
     WorkflowStatus.READY, WorkflowStatus.FAILED, WorkflowStatus.SUCCEEDED],
)
def test_non_running_checkpoint_cannot_dispatch(status: WorkflowStatus) -> None:
    state = _running_state().model_copy(update={"status": status})
    with pytest.raises(WorkflowTransitionError, match="must be running"):
        require_dispatch_authorization(state, approval=_approval(state))


@pytest.mark.parametrize("attempt,max_attempts", [(0, 3), (4, 3), (-1, 3), (1, 0)])
def test_corrupt_attempt_cannot_dispatch(attempt: int, max_attempts: int) -> None:
    state = _running_state().model_copy(
        update={"attempt": attempt, "max_attempts": max_attempts}
    )
    with pytest.raises(WorkflowTransitionError, match="Invalid execution attempt"):
        require_dispatch_authorization(state, approval=_approval(state))


@pytest.mark.parametrize("status", [ApprovalStatus.PENDING, ApprovalStatus.REJECTED])
def test_unapproved_checkpoint_cannot_dispatch(status: ApprovalStatus) -> None:
    state = _running_state()
    with pytest.raises(WorkflowTransitionError, match="Verified approval"):
        require_dispatch_authorization(state, approval=_approval(state, status))


def test_missing_approval_cannot_dispatch() -> None:
    with pytest.raises(WorkflowTransitionError, match="Verified approval"):
        require_dispatch_authorization(_running_state())


def test_unrelated_approval_cannot_dispatch() -> None:
    state = _running_state()
    unrelated = _approval(state).model_copy(update={"action_id": uuid4()})
    with pytest.raises(WorkflowTransitionError, match="Verified approval"):
        require_dispatch_authorization(state, approval=unrelated)
