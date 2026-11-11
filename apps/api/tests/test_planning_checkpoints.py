"""Checkpoint wiring must preserve workflow isolation and fail-closed planning."""
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver

from app.domain.approvals import ApprovalDecision, ApprovalStatus
from app.domain.workflows import WorkflowState, WorkflowStatus
from app.planning_graph import build_planning_graph


def test_checkpointed_planner_can_restore_thread_state_without_dispatch():
    checkpointer = MemorySaver()
    graph = build_planning_graph(checkpointer=checkpointer)
    action_id = uuid4()
    config = {"configurable": {"thread_id": str(action_id)}}
    workflow = WorkflowState(
        action_id=action_id, idempotency_key="checkpoint-test", status=WorkflowStatus.READY
    )
    approval = ApprovalDecision(
        action_id=action_id, status=ApprovalStatus.APPROVED, reviewer_id="reviewer"
    )
    first = graph.invoke(
        {"workflow": workflow, "approval": approval, "next_step": "", "explanation": ""},
        config=config,
    )
    assert first["next_step"] == "claim_outbox"
    snapshot = graph.get_state(config)
    assert snapshot.values["workflow"] == workflow
    assert snapshot.values["approval"] == approval
    assert snapshot.values["next_step"] == "claim_outbox"
    assert snapshot.next == ()
    # The restored plan is advisory, not a durable execution receipt.
    assert "receipt" not in snapshot.values


def test_checkpointed_planner_isolates_action_threads():
    graph = build_planning_graph(checkpointer=MemorySaver())
    first_id, second_id = uuid4(), uuid4()
    first_config = {"configurable": {"thread_id": str(first_id)}}
    second_config = {"configurable": {"thread_id": str(second_id)}}
    graph.invoke(
        {
            "workflow": WorkflowState(
                action_id=first_id, idempotency_key="first", status=WorkflowStatus.PENDING
            ),
            "approval": None,
            "next_step": "",
            "explanation": "",
        },
        config=first_config,
    )
    assert graph.get_state(first_config).values["next_step"] == "request_review"
    assert not graph.get_state(second_config).values
