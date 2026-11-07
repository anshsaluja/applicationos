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


def setup():
    action_id = uuid4()
    state = WorkflowState(action_id=action_id, idempotency_key="job:1", max_attempts=2)
    approved = ApprovalDecision(
        action_id=action_id, status=ApprovalStatus.APPROVED, reviewer_id="reviewer"
    )
    return state, approved


def test_requires_approval_before_ready_and_running():
    state, approved = setup()
    waiting = transition(state, WorkflowStatus.AWAITING_APPROVAL)
    with pytest.raises(WorkflowTransitionError, match="approval"):
        transition(waiting, WorkflowStatus.READY)
    wrong = approved.model_copy(update={"action_id": uuid4()})
    with pytest.raises(WorkflowTransitionError, match="approval"):
        transition(waiting, WorkflowStatus.READY, approval=wrong)
    ready = transition(waiting, WorkflowStatus.READY, approval=approved)
    with pytest.raises(WorkflowTransitionError, match="approval"):
        transition(ready, WorkflowStatus.RUNNING)
    assert transition(ready, WorkflowStatus.RUNNING, approval=approved).attempt == 1


def test_retries_are_bounded_and_terminal_success_cannot_restart():
    state, approved = setup()
    state = transition(state, WorkflowStatus.AWAITING_APPROVAL)
    state = transition(state, WorkflowStatus.READY, approval=approved)
    for attempt in (1, 2):
        state = transition(state, WorkflowStatus.RUNNING, approval=approved)
        assert state.attempt == attempt
        state = transition(state, WorkflowStatus.FAILED)
        if attempt == 1:
            state = transition(state, WorkflowStatus.READY, approval=approved)
    with pytest.raises(WorkflowTransitionError, match="budget"):
        transition(state, WorkflowStatus.READY, approval=approved)


def test_success_is_terminal_and_duplicate_transition_is_idempotent():
    state, approved = setup()
    state = transition(state, WorkflowStatus.AWAITING_APPROVAL)
    state = transition(state, WorkflowStatus.READY, approval=approved)
    state = transition(state, WorkflowStatus.RUNNING, approval=approved)
    state = transition(state, WorkflowStatus.SUCCEEDED)
    assert transition(state, WorkflowStatus.SUCCEEDED) == state
    with pytest.raises(WorkflowTransitionError, match="Invalid transition"):
        transition(state, WorkflowStatus.RUNNING, approval=approved)


def test_cannot_skip_approval_gate():
    state, approved = setup()
    with pytest.raises(WorkflowTransitionError, match="Invalid transition"):
        transition(state, WorkflowStatus.RUNNING, approval=approved)


def test_idempotent_executable_transitions_still_require_durable_approval():
    state, approved = setup()
    waiting = transition(state, WorkflowStatus.AWAITING_APPROVAL)
    ready = transition(waiting, WorkflowStatus.READY, approval=approved)
    with pytest.raises(WorkflowTransitionError, match="approval"):
        transition(ready, WorkflowStatus.READY)
    assert transition(ready, WorkflowStatus.READY, approval=approved) == ready
    running = transition(ready, WorkflowStatus.RUNNING, approval=approved)
    with pytest.raises(WorkflowTransitionError, match="approval"):
        transition(running, WorkflowStatus.RUNNING)
    assert transition(running, WorkflowStatus.RUNNING, approval=approved) == running


def test_dispatch_guard_requires_running_state_and_current_approval():
    state, approved = setup()
    with pytest.raises(WorkflowTransitionError, match="running"):
        require_dispatch_authorization(state, approval=approved)
    waiting = transition(state, WorkflowStatus.AWAITING_APPROVAL)
    ready = transition(waiting, WorkflowStatus.READY, approval=approved)
    with pytest.raises(WorkflowTransitionError, match="running"):
        require_dispatch_authorization(ready, approval=approved)
    running = transition(ready, WorkflowStatus.RUNNING, approval=approved)
    with pytest.raises(WorkflowTransitionError, match="approval"):
        require_dispatch_authorization(running)
    with pytest.raises(WorkflowTransitionError, match="approval"):
        require_dispatch_authorization(running, approval=approved.model_copy(update={"action_id": uuid4()}))
    rejected = approved.model_copy(update={"status": ApprovalStatus.REJECTED})
    with pytest.raises(WorkflowTransitionError, match="approval"):
        require_dispatch_authorization(running, approval=rejected)
    require_dispatch_authorization(running, approval=approved)
    succeeded = transition(running, WorkflowStatus.SUCCEEDED)
    with pytest.raises(WorkflowTransitionError, match="running"):
        require_dispatch_authorization(succeeded, approval=approved)


def test_dispatch_guard_rejects_invalid_attempt_state():
    state, approved = setup()
    invalid = state.model_copy(update={"status": WorkflowStatus.RUNNING, "attempt": 0})
    with pytest.raises(WorkflowTransitionError, match="attempt"):
        require_dispatch_authorization(invalid, approval=approved)
    invalid = state.model_copy(update={"status": WorkflowStatus.RUNNING, "attempt": 3})
    with pytest.raises(WorkflowTransitionError, match="attempt"):
        require_dispatch_authorization(invalid, approval=approved)
