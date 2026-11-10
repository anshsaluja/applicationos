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
        SimpleNamespace(status=outbox_status, idempotency_key="safe-key")
        if outbox_status else None
    )
    stored_receipt = (
        SimpleNamespace(adapter="synthetic-noop", idempotency_key="safe-key")
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
        SimpleNamespace(status="dispatched", idempotency_key="correct"),
        SimpleNamespace(adapter="synthetic-noop", idempotency_key="wrong"),
    )
    assert plan_persisted_workflow(session, action_id)["next_step"] == "reconcile"


def test_missing_workflow_returns_none(monkeypatch):
    monkeypatch.setattr(
        "app.persisted_planning.WorkflowRepository",
        lambda session: SimpleNamespace(get=lambda key: None),
    )
    assert plan_persisted_workflow(FakeSession(), uuid4()) is None
