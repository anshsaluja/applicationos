"""Fresh-evidence planning must reject checkpoint routing attacks before invocation."""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.domain.approvals import ApprovalDecision, ApprovalStatus
from app.domain.workflows import WorkflowState, WorkflowStatus
from app.planning_graph import plan_with_fresh_evidence


class RecordingGraph:
    def __init__(self):
        self.calls = []

    def invoke(self, payload, config=None):
        self.calls.append((payload, config))
        return {"next_step": "request_review", "explanation": "stub"}


def test_revoked_approval_is_explicitly_cleared_from_checkpoint_input():
    action_id = uuid4()
    workflow = WorkflowState(
        action_id=action_id, idempotency_key=str(uuid4()), status=WorkflowStatus.READY
    )
    graph = RecordingGraph()
    config = {"configurable": {"thread_id": str(action_id)}}
    result = plan_with_fresh_evidence(graph, workflow=workflow, approval=None, config=config)
    assert result["next_step"] == "request_review"
    assert len(graph.calls) == 1
    payload, actual_config = graph.calls[0]
    assert payload["approval"] is None
    assert payload["next_step"] == ""
    assert payload["explanation"] == ""
    assert actual_config == config


@pytest.mark.parametrize(
    "routing",
    [
        {"configurable": {"thread_id": "another-action"}},
        {"configurable": {"thread_id": "another-action", "checkpoint_ns": ""}},
        {"configurable": {"thread_id": "placeholder", "checkpoint_id": "old"}},
        {"configurable": {"thread_id": "placeholder", "checkpoint_ns": "foreign"}},
        {"configurable": {"thread_id": "placeholder", "checkpoint_map": {}}},
        {"configurable": {"thread_id": "placeholder"}, "metadata": {"trusted": True}},
        {"configurable": {"thread_id": "placeholder"}, "callbacks": []},
    ],
)
def test_untrusted_checkpoint_routing_never_invokes_graph(routing):
    action_id = uuid4()
    workflow = WorkflowState(
        action_id=action_id, idempotency_key=str(uuid4()), status=WorkflowStatus.READY
    )
    routing["configurable"]["thread_id"] = (
        str(action_id) if routing["configurable"]["thread_id"] == "placeholder"
        else routing["configurable"]["thread_id"]
    )
    graph = RecordingGraph()
    with pytest.raises(ValueError):
        plan_with_fresh_evidence(graph, workflow=workflow, approval=None, config=routing)
    assert graph.calls == []


def test_foreign_approval_cannot_be_written_into_checkpoint():
    action_id = uuid4()
    workflow = WorkflowState(
        action_id=action_id, idempotency_key=str(uuid4()), status=WorkflowStatus.READY
    )
    approval = ApprovalDecision(
        action_id=uuid4(), status=ApprovalStatus.APPROVED, reviewer_id="reviewer"
    )
    graph = RecordingGraph()
    with pytest.raises(ValueError, match="action_id"):
        plan_with_fresh_evidence(
            graph,
            workflow=workflow,
            approval=approval,
            config={"configurable": {"thread_id": str(action_id)}},
        )
    assert graph.calls == []
