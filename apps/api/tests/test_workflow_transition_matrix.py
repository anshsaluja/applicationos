"""Exhaustive state-machine edge coverage for workflow transition policy.

These checks are intentionally database-independent; PostgreSQL transaction
atomicity is exercised separately by the integration suite.
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


def _state(status: WorkflowStatus) -> WorkflowState:
    return WorkflowState(
        action_id=uuid4(),
        idempotency_key="stable-key",
        status=status,
        attempt=1 if status in {WorkflowStatus.RUNNING, WorkflowStatus.SUCCEEDED, WorkflowStatus.FAILED} else 0,
        max_attempts=3,
    )


def _approval(state: WorkflowState) -> ApprovalDecision:
    return ApprovalDecision(
        action_id=state.action_id,
        reviewer_id="reviewer",
        status=ApprovalStatus.APPROVED,
    )


@pytest.mark.parametrize("source", list(WorkflowStatus))
@pytest.mark.parametrize("target", list(WorkflowStatus))
def test_transition_matrix_never_mutates_input_and_only_allows_defined_edges(
    source: WorkflowStatus, target: WorkflowStatus
) -> None:
    state = _state(source)
    snapshot = state.model_dump()
    allowed = {
        WorkflowStatus.PENDING: {WorkflowStatus.AWAITING_APPROVAL},
        WorkflowStatus.AWAITING_APPROVAL: {WorkflowStatus.READY, WorkflowStatus.FAILED},
        WorkflowStatus.READY: {WorkflowStatus.RUNNING},
        WorkflowStatus.RUNNING: {WorkflowStatus.SUCCEEDED, WorkflowStatus.FAILED},
        WorkflowStatus.SUCCEEDED: set(),
        WorkflowStatus.FAILED: {WorkflowStatus.READY},
    }
    approval = _approval(state)
    if target == source or target in allowed[source]:
        updated = transition(state, target, approval=approval)
        assert updated.status == target
        assert updated.action_id == state.action_id
        assert updated.idempotency_key == state.idempotency_key
        assert updated is not state
        assert updated.attempt == state.attempt + (target == WorkflowStatus.RUNNING and source != target)
    else:
        with pytest.raises(WorkflowTransitionError, match="Invalid transition"):
            transition(state, target, approval=approval)
    assert state.model_dump() == snapshot


@pytest.mark.parametrize("status", [WorkflowStatus.PENDING, WorkflowStatus.AWAITING_APPROVAL, WorkflowStatus.READY, WorkflowStatus.FAILED, WorkflowStatus.SUCCEEDED])
def test_dispatch_denies_every_nonrunning_state(status: WorkflowStatus) -> None:
    state = _state(status)
    with pytest.raises(WorkflowTransitionError, match="must be running"):
        require_dispatch_authorization(state, approval=_approval(state))


@pytest.mark.parametrize("attempt", [0, 4, 999])
def test_dispatch_denies_invalid_attempt_even_with_approval(attempt: int) -> None:
    state = _state(WorkflowStatus.RUNNING).model_copy(update={"attempt": attempt})
    with pytest.raises(WorkflowTransitionError, match="Invalid execution attempt"):
        require_dispatch_authorization(state, approval=_approval(state))


def test_replayed_running_transition_never_consumes_another_attempt() -> None:
    state = _state(WorkflowStatus.RUNNING)
    replay = transition(state, WorkflowStatus.RUNNING, approval=_approval(state))
    assert replay.attempt == state.attempt
    assert replay is not state
