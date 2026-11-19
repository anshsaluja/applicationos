"""Fresh-evidence planner must not write an action into another checkpoint thread."""

from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.domain.approvals import ApprovalDecision, ApprovalStatus
from app.domain.workflows import WorkflowState, WorkflowStatus
from app.planning_graph import build_planning_graph, plan_with_fresh_evidence


def _workflow(action_id):
    return WorkflowState(
        action_id=action_id,
        idempotency_key=str(action_id),
        status=WorkflowStatus.READY,
    )


def test_fresh_evidence_rejects_cross_action_checkpoint_without_mutating_store():
    graph = build_planning_graph(checkpointer=MemorySaver())
    first_id, second_id = uuid4(), uuid4()
    config = {"configurable": {"thread_id": str(first_id)}}
    approval = ApprovalDecision(
        action_id=first_id, status=ApprovalStatus.APPROVED, reviewer_id="reviewer"
    )
    first = plan_with_fresh_evidence(
        graph, workflow=_workflow(first_id), approval=approval, config=config
    )
    assert first["next_step"] == "claim_outbox"

    with pytest.raises(ValueError, match="must match workflow action_id"):
        plan_with_fresh_evidence(
            graph, workflow=_workflow(second_id), approval=None, config=config
        )

    checkpoint = graph.get_state(config).values
    assert checkpoint["workflow"].action_id == first_id
    assert checkpoint["approval"] == approval


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"configurable": None},
        {"configurable": {}},
        {"configurable": {"thread_id": "other"}},
        {"configurable": {"thread_id": 123}},
    ],
)
def test_fresh_evidence_rejects_missing_or_mismatched_thread(config):
    graph = build_planning_graph(checkpointer=MemorySaver())
    with pytest.raises(ValueError, match="Checkpoint"):
        plan_with_fresh_evidence(
            graph, workflow=_workflow(uuid4()), approval=None, config=config
        )


def test_fresh_evidence_clears_approval_on_same_action_replan():
    graph = build_planning_graph(checkpointer=MemorySaver())
    action_id = uuid4()
    config = {"configurable": {"thread_id": str(action_id)}}
    approval = ApprovalDecision(
        action_id=action_id, status=ApprovalStatus.APPROVED, reviewer_id="reviewer"
    )
    assert plan_with_fresh_evidence(
        graph, workflow=_workflow(action_id), approval=approval, config=config
    )["next_step"] == "claim_outbox"
    assert plan_with_fresh_evidence(
        graph, workflow=_workflow(action_id), approval=None, config=config
    )["next_step"] == "request_review"
    assert graph.get_state(config).values["approval"] is None
