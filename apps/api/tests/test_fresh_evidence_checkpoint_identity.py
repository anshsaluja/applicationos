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
    with pytest.raises(ValueError, match="Checkpoint|Fresh planning"):
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


def test_foreign_approval_rejected_without_overwriting_existing_checkpoint():
    graph = build_planning_graph(checkpointer=MemorySaver())
    action_id = uuid4()
    config = {"configurable": {"thread_id": str(action_id)}}
    own_approval = ApprovalDecision(
        action_id=action_id, status=ApprovalStatus.APPROVED, reviewer_id="reviewer"
    )
    plan_with_fresh_evidence(
        graph, workflow=_workflow(action_id), approval=own_approval, config=config
    )
    original = graph.get_state(config).values
    foreign_approval = ApprovalDecision(
        action_id=uuid4(), status=ApprovalStatus.APPROVED, reviewer_id="other"
    )
    with pytest.raises(ValueError, match="Approval action_id must match"):
        plan_with_fresh_evidence(
            graph, workflow=_workflow(action_id), approval=foreign_approval, config=config
        )
    assert graph.get_state(config).values == original


def test_foreign_approval_rejected_without_creating_checkpoint():
    graph = build_planning_graph(checkpointer=MemorySaver())
    action_id = uuid4()
    config = {"configurable": {"thread_id": str(action_id)}}
    foreign_approval = ApprovalDecision(
        action_id=uuid4(), status=ApprovalStatus.APPROVED, reviewer_id="other"
    )
    with pytest.raises(ValueError, match="Approval action_id must match"):
        plan_with_fresh_evidence(
            graph, workflow=_workflow(action_id), approval=foreign_approval, config=config
        )
    assert graph.get_state(config).values == {}


@pytest.mark.parametrize("extra", [
    {"checkpoint_map": {"parent": "foreign"}},
    {"checkpoint_id": None},
    {"checkpoint_ns": "other"},
    {"custom_routing": "another-thread"},
])
def test_fresh_evidence_rejects_checkpoint_routing_overrides_without_writes(extra):
    graph = build_planning_graph(checkpointer=MemorySaver())
    action_id = uuid4()
    base = {"configurable": {"thread_id": str(action_id)}}
    approval = ApprovalDecision(
        action_id=action_id, status=ApprovalStatus.APPROVED, reviewer_id="reviewer"
    )
    plan_with_fresh_evidence(graph, workflow=_workflow(action_id), approval=approval, config=base)
    original = graph.get_state(base).values
    overridden = {"configurable": {**base["configurable"], **extra}}
    with pytest.raises(ValueError, match="checkpoint|Checkpoint|Fresh planning"):
        plan_with_fresh_evidence(
            graph, workflow=_workflow(action_id), approval=None, config=overridden
        )
    assert graph.get_state(base).values == original


@pytest.mark.parametrize("override", [
    {"metadata": {"checkpoint_id": "old"}},
    {"callbacks": []},
    {"recursion_limit": 1},
    {"tags": ["foreign"]},
    {"configurable": {"thread_id": "other"}},
])
def test_fresh_evidence_rejects_top_level_config_overrides_without_writes(override):
    graph = build_planning_graph(checkpointer=MemorySaver())
    action_id = uuid4()
    base = {"configurable": {"thread_id": str(action_id)}}
    approval = ApprovalDecision(
        action_id=action_id, status=ApprovalStatus.APPROVED, reviewer_id="reviewer"
    )
    plan_with_fresh_evidence(graph, workflow=_workflow(action_id), approval=approval, config=base)
    before = graph.get_state(base)
    # Even if the override supplies another configurable mapping, the caller
    # must not alter this action's saved approval or routing history.
    with pytest.raises(ValueError, match="checkpoint|Checkpoint|Fresh planning"):
        plan_with_fresh_evidence(
            graph, workflow=_workflow(action_id), approval=None,
            config={**base, **override},
        )
    after = graph.get_state(base)
    assert after.values == before.values
    assert after.config == before.config
