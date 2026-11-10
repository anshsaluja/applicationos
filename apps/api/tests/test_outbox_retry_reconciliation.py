"""Regression: a quarantined dispatch intent must not be silently reused on retry."""

from uuid import uuid4

import pytest

from app.domain.approvals import ApprovalStatus
from app.domain.workflows import WorkflowState, WorkflowStatus, WorkflowTransitionError
from app.persistence import (
    ApprovalRepository,
    WorkflowOutboxRepository,
    WorkflowRepository,
    build_session_factory,
    session_scope,
)


def test_recovered_outbox_intent_blocks_retry_across_sessions():
    factory = build_session_factory()
    action_id = uuid4()
    with session_scope(factory) as session:
        workflow = WorkflowRepository(session)
        workflow.create(WorkflowState(action_id=action_id, idempotency_key=f"outbox:{action_id}"))
        workflow.advance(action_id, WorkflowStatus.AWAITING_APPROVAL)
        ApprovalRepository(session).decide(
            action_id, ApprovalStatus.APPROVED, reviewer_id="test-reviewer"
        )
        workflow.advance(action_id, WorkflowStatus.READY)
        workflow.claim_ready(action_id)
        WorkflowOutboxRepository(session).enqueue_claimed(action_id)

    # A restart cannot prove the pending intent was never observed by a worker.
    with session_scope(factory) as session:
        recovered = WorkflowRepository(session).recover_interrupted(
            action_id, reason="worker stopped"
        )
        assert recovered.status == WorkflowStatus.FAILED

    with session_scope(factory) as session:
        workflow = WorkflowRepository(session)
        with pytest.raises(WorkflowTransitionError, match="reconciliation"):
            workflow.advance(action_id, WorkflowStatus.READY)
        assert workflow.get(action_id).status == WorkflowStatus.FAILED
        assert WorkflowOutboxRepository(session).claim_next_pending(action_id=action_id) is None


def test_failed_workflow_without_dispatch_intent_can_still_retry():
    factory = build_session_factory()
    action_id = uuid4()
    with session_scope(factory) as session:
        workflow = WorkflowRepository(session)
        workflow.create(WorkflowState(action_id=action_id, idempotency_key=f"no-outbox:{action_id}"))
        workflow.advance(action_id, WorkflowStatus.AWAITING_APPROVAL)
        ApprovalRepository(session).decide(
            action_id, ApprovalStatus.APPROVED, reviewer_id="test-reviewer"
        )
        workflow.advance(action_id, WorkflowStatus.READY)
        workflow.claim_ready(action_id)
        workflow.recover_interrupted(action_id, reason="worker stopped")

    with session_scope(factory) as session:
        assert WorkflowRepository(session).advance(
            action_id, WorkflowStatus.READY
        ).status == WorkflowStatus.READY
