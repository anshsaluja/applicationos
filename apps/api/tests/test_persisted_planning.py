"""Persisted planning never recommends replaying uncertain dispatches."""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.approvals import ApprovalDecision, ApprovalStatus
from app.domain.workflows import WorkflowState, WorkflowStatus
from app.persisted_planning import plan_persisted_workflow


class FakeSession:
    def __init__(self, outbox=None, receipt=None):
        self.outbox = outbox
        self.receipt = receipt

    def get(self, model, action_id):
        if model.__name__ == "WorkflowOutboxRow":
            return self.outbox
        if model.__name__ == "SyntheticReceiptRow":
            return self.receipt
        return None


@pytest.mark.parametrize(
    ("status", "outbox_status", "receipt", "expected"),
    [
        (WorkflowStatus.READY, None, False, "claim_outbox"),
        (WorkflowStatus.READY, "pending", False, "reconcile"),
        (WorkflowStatus.READY, "claimed", False, "reconcile"),
        (WorkflowStatus.FAILED, "quarantined", False, "reconcile"),
        (WorkflowStatus.RUNNING, "claimed", True, "reconcile"),
        (WorkflowStatus.SUCCEEDED, None, False, "reconcile"),
        (WorkflowStatus.SUCCEEDED, "dispatched", False, "reconcile"),
        (WorkflowStatus.SUCCEEDED, "dispatched", True, "complete"),
    ],
)
def test_persisted_plan_respects_dispatch_evidence(
    monkeypatch, status, outbox_status, receipt, expected
):
    action_id = uuid4()
    workflow = WorkflowState(
        action_id=action_id, idempotency_key="safe-key", status=status
    )
    approval = ApprovalDecision(
        action_id=action_id, status=ApprovalStatus.APPROVED, reviewer_id="operator"
    )
    monkeypatch.setattr(
        "app.persisted_planning.WorkflowRepository",
        lambda session: SimpleNamespace(get=lambda key: workflow),
    )
    monkeypatch.setattr(
        "app.persisted_planning.ApprovalRepository",
        lambda session: SimpleNamespace(get=lambda key: approval),
    )
    outbox = (
        SimpleNamespace(action_id=action_id, status=outbox_status, idempotency_key="safe-key")
        if outbox_status else None
    )
    stored_receipt = (
        SimpleNamespace(action_id=action_id, adapter="synthetic-noop", idempotency_key="safe-key")
        if receipt else None
    )
    result = plan_persisted_workflow(FakeSession(outbox, stored_receipt), action_id)
    assert result["next_step"] == expected


def test_persisted_plan_rejects_mismatched_receipt(monkeypatch):
    action_id = uuid4()
    workflow = WorkflowState(
        action_id=action_id, idempotency_key="correct", status=WorkflowStatus.SUCCEEDED
    )
    monkeypatch.setattr(
        "app.persisted_planning.WorkflowRepository",
        lambda session: SimpleNamespace(get=lambda key: workflow),
    )
    monkeypatch.setattr(
        "app.persisted_planning.ApprovalRepository",
        lambda session: SimpleNamespace(get=lambda key: None),
    )
    session = FakeSession(
        SimpleNamespace(action_id=action_id, status="dispatched", idempotency_key="correct"),
        SimpleNamespace(action_id=action_id, adapter="synthetic-noop", idempotency_key="wrong"),
    )
    assert plan_persisted_workflow(session, action_id)["next_step"] == "reconcile"


def test_missing_workflow_returns_none(monkeypatch):
    monkeypatch.setattr(
        "app.persisted_planning.WorkflowRepository",
        lambda session: SimpleNamespace(get=lambda key: None),
    )
    assert plan_persisted_workflow(FakeSession(), uuid4()) is None


@pytest.mark.parametrize("mismatched_record", ["outbox", "receipt"])
def test_persisted_plan_rejects_foreign_action_evidence(monkeypatch, mismatched_record):
    action_id = uuid4()
    workflow = WorkflowState(
        action_id=action_id, idempotency_key="safe-key", status=WorkflowStatus.SUCCEEDED
    )
    monkeypatch.setattr(
        "app.persisted_planning.WorkflowRepository",
        lambda session: SimpleNamespace(get=lambda key: workflow),
    )
    monkeypatch.setattr(
        "app.persisted_planning.ApprovalRepository",
        lambda session: SimpleNamespace(get=lambda key: None),
    )
    outbox_id = uuid4() if mismatched_record == "outbox" else action_id
    receipt_id = uuid4() if mismatched_record == "receipt" else action_id
    session = FakeSession(
        SimpleNamespace(action_id=outbox_id, status="dispatched", idempotency_key="safe-key"),
        SimpleNamespace(action_id=receipt_id, adapter="synthetic-noop", idempotency_key="safe-key"),
    )
    assert plan_persisted_workflow(session, action_id)["next_step"] == "reconcile"


@pytest.mark.parametrize("approval_status", [ApprovalStatus.PENDING, ApprovalStatus.REJECTED])
def test_persisted_completion_requires_approved_decision(monkeypatch, approval_status):
    action_id = uuid4()
    workflow = WorkflowState(
        action_id=action_id, idempotency_key="safe-key", status=WorkflowStatus.SUCCEEDED
    )
    approval = ApprovalDecision(action_id=action_id, status=approval_status)
    monkeypatch.setattr(
        "app.persisted_planning.WorkflowRepository",
        lambda session: SimpleNamespace(get=lambda key: workflow),
    )
    monkeypatch.setattr(
        "app.persisted_planning.ApprovalRepository",
        lambda session: SimpleNamespace(get=lambda key: approval),
    )
    session = FakeSession(
        SimpleNamespace(action_id=action_id, status="dispatched", idempotency_key="safe-key"),
        SimpleNamespace(action_id=action_id, adapter="synthetic-noop", idempotency_key="safe-key"),
    )
    assert plan_persisted_workflow(session, action_id)["next_step"] == "reconcile"


def test_persisted_completion_rejects_foreign_approval(monkeypatch):
    action_id = uuid4()
    workflow = WorkflowState(
        action_id=action_id, idempotency_key="safe-key", status=WorkflowStatus.SUCCEEDED
    )
    approval = ApprovalDecision(
        action_id=uuid4(), status=ApprovalStatus.APPROVED, reviewer_id="operator"
    )
    monkeypatch.setattr(
        "app.persisted_planning.WorkflowRepository",
        lambda session: SimpleNamespace(get=lambda key: workflow),
    )
    monkeypatch.setattr(
        "app.persisted_planning.ApprovalRepository",
        lambda session: SimpleNamespace(get=lambda key: approval),
    )
    session = FakeSession(
        SimpleNamespace(action_id=action_id, status="dispatched", idempotency_key="safe-key"),
        SimpleNamespace(action_id=action_id, adapter="synthetic-noop", idempotency_key="safe-key"),
    )
    assert plan_persisted_workflow(session, action_id)["next_step"] == "reconcile"


@pytest.mark.parametrize("reviewer_id", [None, "", "  "])
def test_persisted_completion_requires_identifiable_reviewer(monkeypatch, reviewer_id):
    """A forged approved flag without a reviewer cannot certify completion."""
    action_id = uuid4()
    workflow = WorkflowState(
        action_id=action_id, idempotency_key="safe-key", status=WorkflowStatus.SUCCEEDED
    )
    approval = ApprovalDecision(
        action_id=action_id, status=ApprovalStatus.APPROVED, reviewer_id=reviewer_id
    )
    monkeypatch.setattr(
        "app.persisted_planning.WorkflowRepository",
        lambda session: SimpleNamespace(get=lambda key: workflow),
    )
    monkeypatch.setattr(
        "app.persisted_planning.ApprovalRepository",
        lambda session: SimpleNamespace(get=lambda key: approval),
    )
    session = FakeSession(
        SimpleNamespace(action_id=action_id, status="dispatched", idempotency_key="safe-key"),
        SimpleNamespace(action_id=action_id, adapter="synthetic-noop", idempotency_key="safe-key"),
    )
    assert plan_persisted_workflow(session, action_id)["next_step"] == "reconcile"


def test_durable_plan_uses_action_thread_and_current_database_evidence(monkeypatch):
    """A recovered graph receives fresh approval rather than trusting its checkpoint."""
    action_id = uuid4()
    workflow = WorkflowState(
        action_id=action_id, idempotency_key="safe-key", status=WorkflowStatus.READY
    )
    approval = ApprovalDecision(
        action_id=action_id, status=ApprovalStatus.APPROVED, reviewer_id="operator"
    )
    current = {"approval": approval}
    monkeypatch.setattr(
        "app.persisted_planning.WorkflowRepository",
        lambda session: SimpleNamespace(get=lambda key: workflow),
    )
    monkeypatch.setattr(
        "app.persisted_planning.ApprovalRepository",
        lambda session: SimpleNamespace(get=lambda key: current["approval"]),
    )

    from app.planning_graph import build_planning_graph

    class RecordingGraph:
        def __init__(self):
            self.calls = []
            self.planner = build_planning_graph()

        def invoke(self, state, config):
            self.calls.append((state, config))
            return self.planner.invoke(state, config=config)

    graph = RecordingGraph()
    session = FakeSession()
    assert plan_persisted_workflow(session, action_id, graph=graph)["next_step"] == "claim_outbox"
    current["approval"] = ApprovalDecision(action_id=action_id, status=ApprovalStatus.REJECTED)
    assert plan_persisted_workflow(session, action_id, graph=graph)["next_step"] == "request_review"
    assert len(graph.calls) == 2
    assert graph.calls[0][1] == graph.calls[1][1] == {
        "configurable": {"thread_id": str(action_id)}
    }
    assert graph.calls[0][0]["approval"].status == ApprovalStatus.APPROVED
    assert graph.calls[1][0]["approval"].status == ApprovalStatus.REJECTED


def test_durable_plan_never_invokes_graph_when_dispatch_evidence_exists(monkeypatch):
    """A stale checkpoint cannot replay an action that has an outbox intent."""
    action_id = uuid4()
    workflow = WorkflowState(
        action_id=action_id, idempotency_key="safe-key", status=WorkflowStatus.READY
    )
    monkeypatch.setattr(
        "app.persisted_planning.WorkflowRepository",
        lambda session: SimpleNamespace(get=lambda key: workflow),
    )
    monkeypatch.setattr(
        "app.persisted_planning.ApprovalRepository",
        lambda session: SimpleNamespace(get=lambda key: None),
    )

    class ForbiddenGraph:
        def invoke(self, *args, **kwargs):
            raise AssertionError("Graph must not run when durable dispatch evidence exists")

    session = FakeSession(
        outbox=SimpleNamespace(action_id=action_id, status="claimed", idempotency_key="safe-key")
    )
    assert plan_persisted_workflow(session, action_id, graph=ForbiddenGraph()) == {
        "next_step": "reconcile",
        "explanation": "Existing dispatch evidence forbids planning another claim",
    }


@pytest.mark.parametrize(
    ("outbox_key", "receipt_key", "adapter", "outbox_status"),
    [
        ("wrong-key", "safe-key", "synthetic-noop", "dispatched"),
        ("safe-key", "wrong-key", "synthetic-noop", "dispatched"),
        ("safe-key", "safe-key", "untrusted-adapter", "dispatched"),
        ("safe-key", "safe-key", "synthetic-noop", "claimed"),
    ],
)
def test_completion_requires_matching_dispatch_provenance(
    monkeypatch, outbox_key, receipt_key, adapter, outbox_status
):
    """Neither a forged receipt nor an incomplete dispatch proves success."""
    action_id = uuid4()
    workflow = WorkflowState(
        action_id=action_id, idempotency_key="safe-key", status=WorkflowStatus.SUCCEEDED
    )
    approval = ApprovalDecision(
        action_id=action_id, status=ApprovalStatus.APPROVED, reviewer_id="operator"
    )
    monkeypatch.setattr(
        "app.persisted_planning.WorkflowRepository",
        lambda session: SimpleNamespace(get=lambda key: workflow),
    )
    monkeypatch.setattr(
        "app.persisted_planning.ApprovalRepository",
        lambda session: SimpleNamespace(get=lambda key: approval),
    )
    session = FakeSession(
        SimpleNamespace(action_id=action_id, status=outbox_status, idempotency_key=outbox_key),
        SimpleNamespace(action_id=action_id, adapter=adapter, idempotency_key=receipt_key),
    )
    assert plan_persisted_workflow(session, action_id)["next_step"] == "reconcile"
