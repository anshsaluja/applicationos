"""Workflow retry lifecycle and terminal-state regression tests.

These pure-policy tests complement PostgreSQL outbox and restart integration tests.
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


def _new_workflow(*, max_attempts=3):
    return WorkflowState(
        action_id=uuid4(),
        idempotency_key=str(uuid4()),
        max_attempts=max_attempts,
    )


def _approved(state):
    return ApprovalDecision(
        action_id=state.action_id,
        status=ApprovalStatus.APPROVED,
        reviewer_id="verified-reviewer",
    )


def test_retry_lifecycle_preserves_identity_and_never_exceeds_budget():
    pending = _new_workflow(max_attempts=2)
    approval = _approved(pending)
    awaiting = transition(pending, WorkflowStatus.AWAITING_APPROVAL)
    ready = transition(awaiting, WorkflowStatus.READY, approval=approval)

    for expected_attempt in (1, 2):
        running = transition(ready, WorkflowStatus.RUNNING, approval=approval)
        require_dispatch_authorization(running, approval=approval)
        assert running.attempt == expected_attempt
        assert running.action_id == pending.action_id
        assert running.idempotency_key == pending.idempotency_key
        assert pending.status == WorkflowStatus.PENDING
        failed = transition(running, WorkflowStatus.FAILED)
        assert failed.attempt == expected_attempt
        if expected_attempt < 2:
            ready = transition(failed, WorkflowStatus.READY, approval=approval)

    with pytest.raises(WorkflowTransitionError, match="Retry budget exhausted"):
        transition(failed, WorkflowStatus.READY, approval=approval)


@pytest.mark.parametrize("target", list(WorkflowStatus))
def test_succeeded_is_terminal_even_with_valid_approval(target):
    state = _new_workflow()
    approval = _approved(state)
    succeeded = state.model_copy(update={"status": WorkflowStatus.SUCCEEDED, "attempt": 1})
    if target == WorkflowStatus.SUCCEEDED:
        replay = transition(succeeded, target, approval=approval)
        assert replay == succeeded
        assert replay is not succeeded
    else:
        with pytest.raises(WorkflowTransitionError, match="Invalid transition"):
            transition(succeeded, target, approval=approval)


@pytest.mark.parametrize("status", [WorkflowStatus.READY, WorkflowStatus.RUNNING])
def test_executable_state_replay_fails_closed_after_approval_revocation(status):
    state = _new_workflow().model_copy(update={"status": status, "attempt": 1})
    with pytest.raises(WorkflowTransitionError, match="Verified approval"):
        transition(state, status, approval=None)
    rejected = ApprovalDecision(
        action_id=state.action_id,
        status=ApprovalStatus.REJECTED,
        reviewer_id="verified-reviewer",
        reason="No longer authorized",
    )
    with pytest.raises(WorkflowTransitionError, match="Verified approval"):
        transition(state, status, approval=rejected)


def test_retry_execution_clears_previous_error_only_when_running():
    state = _new_workflow().model_copy(
        update={
            "status": WorkflowStatus.FAILED,
            "attempt": 1,
            "last_error": "temporary failure",
        }
    )
    approval = _approved(state)
    ready = transition(state, WorkflowStatus.READY, approval=approval)
    assert ready.last_error == "temporary failure"
    running = transition(ready, WorkflowStatus.RUNNING, approval=approval)
    assert running.last_error is None
    assert running.attempt == 2
    assert state.last_error == "temporary failure"
