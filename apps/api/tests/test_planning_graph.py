"""LangGraph planning cannot authorize execution or replay uncertain actions."""
from uuid import uuid4

import pytest

from app.domain.approvals import ApprovalDecision, ApprovalStatus
from app.domain.workflows import WorkflowState, WorkflowStatus
from app.planning_graph import build_planning_graph


@pytest.mark.parametrize(
    ("status", "approval_status", "expected"),
    [
        (WorkflowStatus.PENDING, ApprovalStatus.APPROVED, "request_review"),
        (WorkflowStatus.AWAITING_APPROVAL, None, "request_review"),
        (WorkflowStatus.AWAITING_APPROVAL, ApprovalStatus.PENDING, "request_review"),
        (WorkflowStatus.AWAITING_APPROVAL, ApprovalStatus.REJECTED, "request_review"),
        (WorkflowStatus.AWAITING_APPROVAL, ApprovalStatus.APPROVED, "persist_ready"),
        (WorkflowStatus.READY, None, "request_review"),
        (WorkflowStatus.READY, ApprovalStatus.APPROVED, "claim_outbox"),
        (WorkflowStatus.RUNNING, ApprovalStatus.APPROVED, "reconcile"),
        (WorkflowStatus.FAILED, ApprovalStatus.APPROVED, "reconcile"),
        (WorkflowStatus.SUCCEEDED, None, "complete"),
    ],
)
def test_planning_graph_fails_closed(status, approval_status, expected):
    action_id = uuid4()
    workflow = WorkflowState(
        action_id=action_id, idempotency_key="synthetic", status=status
    )
    approval = (
        ApprovalDecision(
            action_id=action_id, status=approval_status, reviewer_id="reviewer"
        )
        if approval_status is not None
        else None
    )
    result = build_planning_graph().invoke(
        {"workflow": workflow, "approval": approval, "next_step": "", "explanation": ""}
    )
    assert result["next_step"] == expected
    assert result["workflow"] == workflow


def test_planning_graph_rejects_approval_for_different_action():
    workflow = WorkflowState(
        action_id=uuid4(), idempotency_key="different-action", status=WorkflowStatus.READY
    )
    approval = ApprovalDecision(
        action_id=uuid4(), status=ApprovalStatus.APPROVED, reviewer_id="reviewer"
    )
    result = build_planning_graph().invoke(
        {"workflow": workflow, "approval": approval, "next_step": "", "explanation": ""}
    )
    assert result["next_step"] == "request_review"


def test_planning_graph_rejects_unattributed_approval():
    action_id = uuid4()
    workflow = WorkflowState(
        action_id=action_id, idempotency_key="unattributed", status=WorkflowStatus.READY
    )
    approval = ApprovalDecision(action_id=action_id, status=ApprovalStatus.APPROVED)
    result = build_planning_graph().invoke(
        {"workflow": workflow, "approval": approval, "next_step": "", "explanation": ""}
    )
    assert result["next_step"] == "request_review"
