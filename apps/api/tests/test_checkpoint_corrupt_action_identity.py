"""Reject malformed recovered action identities before checkpoint writes."""

from uuid import uuid4

import pytest

from app.domain.approvals import ApprovalDecision, ApprovalStatus
from app.domain.workflows import WorkflowState, WorkflowStatus
from app.planning_graph import plan_with_fresh_evidence


class RecordingGraph:
    def __init__(self):
        self.calls = 0

    def invoke(self, state, config=None):
        self.calls += 1
        return state


@pytest.mark.parametrize("corrupt_id", ["not-a-uuid", None, 123, True])
def test_corrupted_workflow_identity_never_reaches_graph(corrupt_id):
    action_id = uuid4()
    workflow = WorkflowState(
        action_id=action_id, status=WorkflowStatus.READY, idempotency_key=str(uuid4())
    ).model_copy(update={"action_id": corrupt_id})
    graph = RecordingGraph()
    with pytest.raises(TypeError, match="Workflow action_id must be a UUID"):
        plan_with_fresh_evidence(graph, workflow=workflow, approval=None)
    assert graph.calls == 0


@pytest.mark.parametrize("corrupt_id", ["not-a-uuid", None, 123, True])
def test_corrupted_approval_identity_never_reaches_graph(corrupt_id):
    action_id = uuid4()
    workflow = WorkflowState(
        action_id=action_id, status=WorkflowStatus.READY, idempotency_key=str(uuid4())
    )
    approval = ApprovalDecision(
        action_id=action_id, status=ApprovalStatus.APPROVED, reviewer_id="reviewer"
    ).model_copy(update={"action_id": corrupt_id})
    graph = RecordingGraph()
    with pytest.raises(TypeError, match="Approval action_id must be a UUID"):
        plan_with_fresh_evidence(graph, workflow=workflow, approval=approval)
    assert graph.calls == 0
