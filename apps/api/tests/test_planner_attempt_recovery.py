"""Recovered workflow attempt counters must never produce an executable plan."""

from uuid import uuid4

import pytest

from app.domain.approvals import ApprovalDecision, ApprovalStatus
from app.domain.workflows import WorkflowState, WorkflowStatus
from app.planning_graph import build_planning_graph, plan_with_fresh_evidence


@pytest.mark.parametrize(
    ("status", "attempt", "max_attempts", "expected"),
    [
        (WorkflowStatus.READY, 3, 3, "reconcile"),
        (WorkflowStatus.READY, 4, 3, "reconcile"),
        (WorkflowStatus.RUNNING, 0, 3, "reconcile"),
        (WorkflowStatus.SUCCEEDED, 0, 3, "reconcile"),
        (WorkflowStatus.RUNNING, 4, 3, "reconcile"),
        (WorkflowStatus.READY, 2, 3, "claim_outbox"),
        (WorkflowStatus.AWAITING_APPROVAL, 3, 3, "reconcile"),
    ],
)
def test_recovered_attempts_are_not_mistaken_for_dispatch_authorization(
    status: WorkflowStatus, attempt: int, max_attempts: int, expected: str
) -> None:
    action_id = uuid4()
    workflow = WorkflowState(
        action_id=action_id,
        idempotency_key=str(action_id),
        status=status,
        attempt=attempt,
        max_attempts=max_attempts,
    )
    approval = ApprovalDecision(
        action_id=action_id,
        status=ApprovalStatus.APPROVED,
        reviewer_id="reviewer",
    )
    result = plan_with_fresh_evidence(
        build_planning_graph(), workflow=workflow, approval=approval
    )
    assert result["next_step"] == expected
