"""A corrupted repository lookup cannot cross an action checkpoint boundary."""
from types import SimpleNamespace
from uuid import uuid4

from app.domain.workflows import WorkflowState, WorkflowStatus
from app.persisted_planning import plan_persisted_workflow


class ForbiddenSession:
    def get(self, *args, **kwargs):
        raise AssertionError("No dispatch evidence should be read for a foreign workflow")


class ForbiddenGraph:
    def invoke(self, *args, **kwargs):
        raise AssertionError("Foreign workflow must never enter a checkpoint")


def test_foreign_workflow_identity_fails_closed_before_checkpoint(monkeypatch):
    requested_id = uuid4()
    foreign = WorkflowState(
        action_id=uuid4(), idempotency_key="foreign-key", status=WorkflowStatus.READY
    )
    monkeypatch.setattr(
        "app.persisted_planning.WorkflowRepository",
        lambda session: SimpleNamespace(get=lambda action_id: foreign),
    )

    class ForbiddenApprovalRepository:
        def __init__(self, session):
            raise AssertionError("Foreign workflow must not load approval evidence")

    monkeypatch.setattr(
        "app.persisted_planning.ApprovalRepository", ForbiddenApprovalRepository
    )
    assert plan_persisted_workflow(
        ForbiddenSession(), requested_id, graph=ForbiddenGraph()
    ) == {
        "next_step": "reconcile",
        "explanation": "Persisted workflow identity does not match requested action",
    }
