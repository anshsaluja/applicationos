"""Regression coverage for cross-action approval and checkpoint replay boundaries."""

from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver

from app.domain.approvals import ApprovalDecision, ApprovalStatus
from app.domain.workflows import WorkflowState, WorkflowStatus
from app.planning_graph import build_planning_graph


def _invoke(graph, config, action_id, approval):
    return graph.invoke(
        {
            "workflow": WorkflowState(
                action_id=action_id,
                idempotency_key=str(action_id),
                status=WorkflowStatus.READY,
            ),
            "approval": approval,
            "next_step": "",
            "explanation": "",
        },
        config=config,
    )


def test_checkpoint_replay_does_not_transfer_approval_to_another_action():
    graph = build_planning_graph(checkpointer=MemorySaver())
    original_action = uuid4()
    other_action = uuid4()
    config = {"configurable": {"thread_id": str(original_action)}}
    approved = ApprovalDecision(
        action_id=original_action,
        status=ApprovalStatus.APPROVED,
        reviewer_id="reviewer",
    )

    assert _invoke(graph, config, original_action, approved)["next_step"] == "claim_outbox"

    # Even if a caller accidentally reuses a checkpoint thread, the saved
    # decision must not authorize a different action.
    replay = _invoke(graph, config, other_action, approved)
    assert replay["next_step"] == "request_review"
    assert graph.get_state(config).values["workflow"].action_id == other_action


def test_checkpoint_replay_does_not_reuse_approval_when_field_is_missing():
    graph = build_planning_graph(checkpointer=MemorySaver())
    action_id = uuid4()
    config = {"configurable": {"thread_id": str(action_id)}}
    approved = ApprovalDecision(
        action_id=action_id,
        status=ApprovalStatus.APPROVED,
        reviewer_id="reviewer",
    )
    assert _invoke(graph, config, action_id, approved)["next_step"] == "claim_outbox"

    # LangGraph merges partial state updates. A missing approval key would
    # otherwise preserve an earlier approval, so callers must pass None.
    replay = _invoke(graph, config, action_id, None)
    assert replay["next_step"] == "request_review"
    assert graph.get_state(config).values["approval"] is None
