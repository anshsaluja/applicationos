"""Regression coverage for persisted approval identity checks at outbox boundaries."""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.domain.workflows import WorkflowState, WorkflowStatus, WorkflowTransitionError
from app.persistence import (
    ApprovalRepository,
    ApprovalRow,
    WorkflowOutboxRepository,
    WorkflowRepository,
)
from test_claim_ready_postgres import factory


def _running(session):
    action_id = uuid4()
    workflows = WorkflowRepository(session)
    workflows.create(WorkflowState(action_id=action_id, idempotency_key=str(uuid4())))
    workflows.advance(action_id, WorkflowStatus.AWAITING_APPROVAL)
    ApprovalRepository(session).decide(action_id, "approved", reviewer_id="reviewer")
    workflows.advance(action_id, WorkflowStatus.READY)
    workflows.claim_ready(action_id)
    return action_id


def test_enqueue_rejects_corrupted_approved_reviewer(factory):
    with factory.begin() as session:
        action_id = _running(session)
        session.get(ApprovalRow, action_id).reviewer_id = "bad reviewer"
        session.flush()
        with pytest.raises(WorkflowTransitionError, match="Persisted approval required"):
            WorkflowOutboxRepository(session).enqueue_claimed(action_id)


def test_pending_claim_quarantines_corrupted_approved_reviewer(factory):
    with factory.begin() as session:
        action_id = _running(session)
        outbox = WorkflowOutboxRepository(session)
        outbox.enqueue_claimed(action_id)
        session.get(ApprovalRow, action_id).reviewer_id = "bad reviewer"
    with factory.begin() as session:
        outbox = WorkflowOutboxRepository(session)
        assert outbox.claim_next_pending(action_id=action_id) is None
        from app.persistence import WorkflowOutboxRow
        assert session.get(WorkflowOutboxRow, action_id).status == "quarantined"
