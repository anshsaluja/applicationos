"""Checkpointed plans must not preserve stale authorization across invocations."""

from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver

from app.domain.approvals import ApprovalDecision, ApprovalStatus
from app.domain.workflows import WorkflowState, WorkflowStatus
from app.planning_graph import build_planning_graph


def _workflow(action_id, status):
    return WorkflowState(
        action_id=action_id, idempotency_key="recovery-test", status=status
    )


def _approval(action_id, status):
    return ApprovalDecision(
        action_id=action_id, status=status, reviewer_id="reviewer"
    )


def _invoke(graph, config, workflow, approval):
    return graph.invoke(
        {
            "workflow": workflow,
            "approval": approval,
            "next_step": "",
            "explanation": "",
        },
        config=config,
    )


def test_checkpointed_plan_rechecks_revoked_approval():
    graph = build_planning_graph(checkpointer=MemorySaver())
    action_id = uuid4()
    config = {"configurable": {"thread_id": str(action_id)}}
    workflow = _workflow(action_id, WorkflowStatus.READY)

    initial = _invoke(graph, config, workflow, _approval(action_id, ApprovalStatus.APPROVED))
    assert initial["next_step"] == "claim_outbox"

    recovered = _invoke(graph, config, workflow, _approval(action_id, ApprovalStatus.REJECTED))
    assert recovered["next_step"] == "request_review"
    assert graph.get_state(config).values["next_step"] == "request_review"


def test_checkpointed_plan_reconciles_running_action_instead_of_replaying_claim():
    graph = build_planning_graph(checkpointer=MemorySaver())
    action_id = uuid4()
    config = {"configurable": {"thread_id": str(action_id)}}
    approval = _approval(action_id, ApprovalStatus.APPROVED)

    initial = _invoke(graph, config, _workflow(action_id, WorkflowStatus.READY), approval)
    assert initial["next_step"] == "claim_outbox"

    recovered = _invoke(graph, config, _workflow(action_id, WorkflowStatus.RUNNING), approval)
    assert recovered["next_step"] == "reconcile"
    assert graph.get_state(config).values["next_step"] == "reconcile"


def test_checkpointed_plan_reconciles_success_without_receipt():
    graph = build_planning_graph(checkpointer=MemorySaver())
    action_id = uuid4()
    config = {"configurable": {"thread_id": str(action_id)}}
    approval = _approval(action_id, ApprovalStatus.APPROVED)

    _invoke(graph, config, _workflow(action_id, WorkflowStatus.READY), approval)
    recovered = _invoke(graph, config, _workflow(action_id, WorkflowStatus.SUCCEEDED), approval)

    assert recovered["next_step"] == "reconcile"
    assert "receipt" not in graph.get_state(config).values
