"""Malformed LangGraph checkpoint payloads must never authorize outbox claims."""

from uuid import uuid4

import pytest

from app.domain.approvals import ApprovalDecision, ApprovalStatus
from app.domain.workflows import WorkflowState, WorkflowStatus
from app.planning_graph import build_planning_graph


@pytest.mark.parametrize("invalid", [None, {}, {"status": "ready"}, "ready", 42, True])
def test_malformed_recovered_workflow_requires_reconciliation(invalid: object) -> None:
    result = build_planning_graph().invoke(
        {"workflow": invalid, "approval": None, "next_step": "", "explanation": ""}
    )
    assert result["next_step"] == "reconcile"
    assert "Invalid workflow state" in result["explanation"]


@pytest.mark.parametrize("invalid", [{}, {"status": "approved"}, "approved", 42, True, []])
def test_malformed_recovered_approval_cannot_claim_outbox(invalid: object) -> None:
    action_id = uuid4()
    workflow = WorkflowState(
        action_id=action_id, idempotency_key="checkpoint-corruption", status=WorkflowStatus.READY
    )
    result = build_planning_graph().invoke(
        {"workflow": workflow, "approval": invalid, "next_step": "", "explanation": ""}
    )
    assert result["next_step"] == "request_review"


def test_valid_approval_still_reaches_durable_claim_boundary() -> None:
    action_id = uuid4()
    workflow = WorkflowState(
        action_id=action_id, idempotency_key="checkpoint-valid", status=WorkflowStatus.READY
    )
    approval = ApprovalDecision(
        action_id=action_id, status=ApprovalStatus.APPROVED, reviewer_id="reviewer"
    )
    result = build_planning_graph().invoke(
        {"workflow": workflow, "approval": approval, "next_step": "", "explanation": ""}
    )
    assert result["next_step"] == "claim_outbox"
