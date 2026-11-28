"""Corrupted persisted retry budgets must fail closed even on read-only replay.

Pydantic model_copy(update=...) intentionally bypasses validation, mirroring
untrusted values reconstructed from storage or migration mistakes.
"""

from uuid import uuid4

import pytest

from app.domain.workflows import (
    WorkflowState,
    WorkflowStatus,
    WorkflowTransitionError,
    transition,
)


@pytest.mark.parametrize(
    "attempt,max_attempts",
    [(-1, 3), (0, 0), (0, -1), (0, 11), (4, 3)],
)
def test_corrupt_pending_checkpoint_replay_is_rejected(
    attempt: int, max_attempts: int
) -> None:
    state = WorkflowState(
        action_id=uuid4(),
        idempotency_key=str(uuid4()),
    ).model_copy(update={"attempt": attempt, "max_attempts": max_attempts})
    with pytest.raises(WorkflowTransitionError, match="Invalid execution attempt"):
        transition(state, WorkflowStatus.PENDING)


def test_valid_pending_checkpoint_replay_remains_idempotent() -> None:
    state = WorkflowState(action_id=uuid4(), idempotency_key=str(uuid4()))
    replayed = transition(state, WorkflowStatus.PENDING)
    assert replayed == state
    assert replayed is not state
