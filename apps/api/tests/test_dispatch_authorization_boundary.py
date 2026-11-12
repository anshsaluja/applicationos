"""Pure dispatch-authorization boundary regressions.

These tests do not replace PostgreSQL transaction and outbox concurrency tests.
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


def _state(status=WorkflowStatus.RUNNING, *, attempt=1, max_attempts=3):
    return WorkflowState(
        action_id=uuid4(),
        status=status,
        attempt=attempt,
        max_attempts=max_attempts,
        idempotency_key=str(uuid4()),
    )


def _approval(state, status=ApprovalStatus.APPROVED):
    return ApprovalDecision(
        action_id=state.action_id, status=status, reviewer_id="reviewer-1"
    )


@pytest.mark.parametrize("status", list(WorkflowStatus))
def test_dispatch_only_permits_running_status(status):
    state = _state(status)
    approval = _approval(state)
    if status == WorkflowStatus.RUNNING:
        require_dispatch_authorization(state, approval=approval)
    else:
        with pytest.raises(WorkflowTransitionError, match="running"):
            require_dispatch_authorization(state, approval=approval)


@pytest.mark.parametrize("approval_kind", ["missing", "pending", "rejected", "wrong-action", "blank-reviewer"])
def test_dispatch_rechecks_current_approval(approval_kind):
    state = _state()
    approval = _approval(state)
    if approval_kind == "missing":
        approval = None
    elif approval_kind == "pending":
        approval = _approval(state, ApprovalStatus.PENDING)
    elif approval_kind == "rejected":
        approval = _approval(state, ApprovalStatus.REJECTED)
    elif approval_kind == "wrong-action":
        approval = ApprovalDecision(
            action_id=uuid4(), status=ApprovalStatus.APPROVED, reviewer_id="reviewer-1"
        )
    else:
        approval = ApprovalDecision(
            action_id=state.action_id, status=ApprovalStatus.APPROVED, reviewer_id="  "
        )
    with pytest.raises(WorkflowTransitionError, match="approval"):
        require_dispatch_authorization(state, approval=approval)


@pytest.mark.parametrize("attempt", [0, 4])
def test_dispatch_rejects_invalid_attempt_counters(attempt):
    state = _state(attempt=attempt)
    with pytest.raises(WorkflowTransitionError, match="attempt"):
        require_dispatch_authorization(state, approval=_approval(state))


def test_running_transition_increments_attempt_once_and_rechecks_approval():
    ready = _state(WorkflowStatus.READY, attempt=0)
    approved = _approval(ready)
    running = transition(ready, WorkflowStatus.RUNNING, approval=approved)
    assert running.attempt == 1
    assert ready.attempt == 0
    assert transition(running, WorkflowStatus.RUNNING, approval=approved).attempt == 1
    with pytest.raises(WorkflowTransitionError, match="approval"):
        transition(running, WorkflowStatus.RUNNING, approval=None)


def test_retry_budget_blocks_another_execution_attempt():
    failed = _state(WorkflowStatus.FAILED, attempt=3)
    with pytest.raises(WorkflowTransitionError, match="Retry budget exhausted"):
        transition(failed, WorkflowStatus.READY, approval=_approval(failed))
