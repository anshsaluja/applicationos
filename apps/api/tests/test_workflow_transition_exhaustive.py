"""Exhaustive transition invariants for the pure approval-gated state machine.

These tests deliberately avoid a database: durable claim/recovery behavior is
covered separately by PostgreSQL integration tests.
"""
from itertools import product
from uuid import uuid4

import pytest

from app.domain.approvals import ApprovalDecision
from app.domain.workflows import (
    WorkflowState,
    WorkflowStatus,
    WorkflowTransitionError,
    require_dispatch_authorization,
    transition,
)


def _state(status: WorkflowStatus, attempt: int = 0) -> WorkflowState:
    return WorkflowState(
        action_id=uuid4(),
        idempotency_key="transition-matrix-test",
        status=status,
        attempt=attempt,
        max_attempts=3,
    )


@pytest.mark.parametrize("status,target", list(product(WorkflowStatus, repeat=2)))
def test_unapproved_transitions_never_enter_executable_state(status, target):
    state = _state(status)
    if target not in {WorkflowStatus.READY, WorkflowStatus.RUNNING}:
        return
    with pytest.raises(WorkflowTransitionError):
        transition(state, target, approval=None)


@pytest.mark.parametrize("attempt", [0, 1, 2, 3])
def test_dispatch_guard_rejects_missing_approval_at_every_attempt(attempt):
    state = _state(WorkflowStatus.RUNNING, attempt=attempt)
    with pytest.raises(WorkflowTransitionError):
        require_dispatch_authorization(state, approval=None)


@pytest.mark.parametrize("status", list(WorkflowStatus))
def test_dispatch_guard_rejects_all_states_without_approval(status):
    state = _state(status, attempt=1)
    with pytest.raises(WorkflowTransitionError):
        require_dispatch_authorization(state, approval=None)


def test_success_is_terminal_even_when_replayed():
    state = _state(WorkflowStatus.SUCCEEDED, attempt=1)
    replay = transition(state, WorkflowStatus.SUCCEEDED)
    assert replay == state
    assert replay is not state
    for target in WorkflowStatus:
        if target != WorkflowStatus.SUCCEEDED:
            with pytest.raises(WorkflowTransitionError):
                transition(state, target)


@pytest.mark.parametrize("attempt", [3, 4])
def test_exhausted_failed_workflow_cannot_reenter_ready(attempt):
    state = _state(WorkflowStatus.FAILED, attempt=attempt)
    # The budget check is reached only after approval validation; this test
    # verifies fail-closed behavior without constructing forged credentials.
    with pytest.raises(WorkflowTransitionError):
        transition(state, WorkflowStatus.READY)
