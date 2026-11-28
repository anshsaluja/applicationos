"""Fail-closed planning entrypoint regression tests for checkpoint replay."""

from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.domain.approvals import ApprovalDecision, ApprovalStatus
from app.domain.workflows import WorkflowState, WorkflowStatus
from app.planning_graph import build_planning_graph, plan_with_fresh_evidence


def test_fresh_evidence_entrypoint_clears_prior_checkpoint_approval():
    action_id = uuid4()
    config = {"configurable": {"thread_id": str(action_id)}}
    workflow = WorkflowState(
        action_id=action_id, idempotency_key=str(action_id), status=WorkflowStatus.READY
    )
    approved = ApprovalDecision(
        action_id=action_id, status=ApprovalStatus.APPROVED, reviewer_id="reviewer"
    )
    graph = build_planning_graph(checkpointer=MemorySaver())
    first = plan_with_fresh_evidence(
        graph, workflow=workflow, approval=approved, config=config
    )
    assert first["next_step"] == "claim_outbox"

    restored = build_planning_graph(checkpointer=graph.checkpointer)
    denied = plan_with_fresh_evidence(
        restored, workflow=workflow, approval=None, config=config
    )
    assert denied["next_step"] == "request_review"
    assert restored.get_state(config).values["approval"] is None


def test_fresh_evidence_entrypoint_rejects_malformed_caller_evidence():
    graph = build_planning_graph()
    workflow = WorkflowState(
        action_id=uuid4(), idempotency_key=str(uuid4()), status=WorkflowStatus.READY
    )
    with pytest.raises(TypeError, match="workflow"):
        plan_with_fresh_evidence(graph, workflow=None, approval=None)
    with pytest.raises(TypeError, match="approval"):
        plan_with_fresh_evidence(graph, workflow=workflow, approval={"status": "approved"})


@pytest.mark.parametrize(
    "extra",
    [
        {"checkpoint_id": "old-checkpoint"},
        {"checkpoint_id": None},
        {"checkpoint_ns": "other-workflow"},
    ],
)
def test_fresh_evidence_rejects_historical_checkpoint_selection_without_writing(extra):
    action_id = uuid4()
    workflow = WorkflowState(
        action_id=action_id, idempotency_key=str(action_id), status=WorkflowStatus.READY
    )
    approval = ApprovalDecision(
        action_id=action_id, status=ApprovalStatus.APPROVED, reviewer_id="reviewer"
    )
    graph = build_planning_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(action_id)}}
    first = plan_with_fresh_evidence(graph, workflow=workflow, approval=approval, config=config)
    assert first["next_step"] == "claim_outbox"
    before = graph.get_state(config)
    with pytest.raises(ValueError, match="checkpoint_id|namespace"):
        plan_with_fresh_evidence(
            graph,
            workflow=workflow,
            approval=None,
            config={"configurable": {"thread_id": str(action_id), **extra}},
        )
    after = graph.get_state(config)
    assert after.values == before.values
    assert after.config == before.config


def test_fresh_evidence_accepts_explicit_default_namespace():
    action_id = uuid4()
    workflow = WorkflowState(
        action_id=action_id, idempotency_key=str(action_id), status=WorkflowStatus.READY
    )
    graph = build_planning_graph(checkpointer=MemorySaver())
    result = plan_with_fresh_evidence(
        graph,
        workflow=workflow,
        approval=None,
        config={"configurable": {"thread_id": str(action_id), "checkpoint_ns": ""}},
    )
    assert result["next_step"] == "request_review"
