"""Regression tests for planner recompilation against an existing checkpoint store.

This exercises checkpoint restoration without suggesting that in-memory storage
survives a process restart; durable PostgreSQL restart coverage is separate.
"""

from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver

from app.domain.approvals import ApprovalDecision, ApprovalStatus
from app.domain.workflows import WorkflowState, WorkflowStatus
from app.planning_graph import build_planning_graph


def _state(action_id, approval):
    return {
        "workflow": WorkflowState(
            action_id=action_id,
            idempotency_key=str(action_id),
            status=WorkflowStatus.READY,
        ),
        "approval": approval,
        "next_step": "",
        "explanation": "",
    }


def test_recompiled_planner_restores_checkpoint_but_requires_fresh_approval():
    store = MemorySaver()
    action_id = uuid4()
    config = {"configurable": {"thread_id": str(action_id)}}
    approval = ApprovalDecision(
        action_id=action_id,
        status=ApprovalStatus.APPROVED,
        reviewer_id="reviewer",
    )

    first_graph = build_planning_graph(checkpointer=store)
    assert first_graph.invoke(_state(action_id, approval), config=config)["next_step"] == "claim_outbox"

    # Recompilation with the same store simulates reconstructing the graph
    # object, not a durable database/process restart.
    restored_graph = build_planning_graph(checkpointer=store)
    checkpoint = restored_graph.get_state(config)
    assert checkpoint.values["workflow"].action_id == action_id
    assert checkpoint.values["approval"].status == ApprovalStatus.APPROVED

    # A fresh caller must explicitly clear stale checkpoint authorization.
    result = restored_graph.invoke(_state(action_id, None), config=config)
    assert result["next_step"] == "request_review"
    assert restored_graph.get_state(config).values["approval"] is None


def test_recompiled_planner_cannot_transfer_checkpoint_approval_to_new_action():
    store = MemorySaver()
    original_action = uuid4()
    next_action = uuid4()
    config = {"configurable": {"thread_id": str(original_action)}}
    approval = ApprovalDecision(
        action_id=original_action,
        status=ApprovalStatus.APPROVED,
        reviewer_id="reviewer",
    )
    build_planning_graph(checkpointer=store).invoke(
        _state(original_action, approval), config=config
    )

    restored_graph = build_planning_graph(checkpointer=store)
    result = restored_graph.invoke(_state(next_action, approval), config=config)
    assert result["next_step"] == "request_review"
    assert restored_graph.get_state(config).values["workflow"].action_id == next_action
