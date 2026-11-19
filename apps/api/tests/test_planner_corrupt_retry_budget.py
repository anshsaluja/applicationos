"""Recovered planner state must never suggest dispatch with invalid retry budgets."""
from uuid import uuid4

import pytest

from app.domain.workflows import WorkflowState, WorkflowStatus
from app.planning_graph import _route


@pytest.mark.parametrize(
    "attempt,max_attempts",
    [(-1, 3), (0, 0), (0, -1), (0, 11), (4, 3)],
)
@pytest.mark.parametrize("status", [WorkflowStatus.READY, WorkflowStatus.AWAITING_APPROVAL])
def test_corrupt_retry_budget_fails_closed_before_approval(
    attempt: int, max_attempts: int, status: WorkflowStatus
) -> None:
    workflow = WorkflowState(action_id=uuid4(), idempotency_key=str(uuid4())).model_copy(
        update={"status": status, "attempt": attempt, "max_attempts": max_attempts}
    )
    result = _route({"workflow": workflow, "approval": None, "next_step": "", "explanation": ""})
    assert result["next_step"] == "reconcile"
    assert "Invalid execution attempt" in result["explanation"]


def test_valid_unapproved_ready_workflow_still_requests_review() -> None:
    workflow = WorkflowState(action_id=uuid4(), idempotency_key=str(uuid4())).model_copy(
        update={"status": WorkflowStatus.READY}
    )
    result = _route({"workflow": workflow, "approval": None, "next_step": "", "explanation": ""})
    assert result["next_step"] == "request_review"
