"""Transactional outbox integration checks; use a disposable PostgreSQL database."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain.workflows import WorkflowState, WorkflowStatus, WorkflowTransitionError
from app.persistence import (
    ApprovalRepository,
    ApprovalRow,
    Base,
    WorkflowOutboxRepository,
    WorkflowOutboxRow,
    WorkflowRepository,
)


@pytest.fixture(scope="module")
def factory():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL required")
    if not url.startswith(("postgresql+psycopg://", "postgresql://")):
        pytest.fail("TEST_DATABASE_URL must use PostgreSQL")
    engine = create_engine(url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def test_outbox_requires_claim_and_persisted_approval(factory):
    action_id = uuid4()
    with factory.begin() as session:
        repo = WorkflowRepository(session)
        repo.create(WorkflowState(action_id=action_id, idempotency_key=str(uuid4())))
        repo.advance(action_id, WorkflowStatus.AWAITING_APPROVAL)
        with pytest.raises(WorkflowTransitionError, match="claimed running"):
            WorkflowOutboxRepository(session).enqueue_claimed(action_id)
        ApprovalRepository(session).decide(action_id, "approved", reviewer_id="test")
        repo.advance(action_id, WorkflowStatus.READY)
        repo.claim_ready(action_id)
        first = WorkflowOutboxRepository(session).enqueue_claimed(action_id)
        second = WorkflowOutboxRepository(session).enqueue_claimed(action_id)
        assert first.action_id == second.action_id
        assert first.idempotency_key == second.idempotency_key
        assert first.status == "pending"


def test_outbox_rollback_is_atomic_with_claim(factory):
    action_id = uuid4()
    with factory.begin() as session:
        repo = WorkflowRepository(session)
        repo.create(WorkflowState(action_id=action_id, idempotency_key=str(uuid4())))
        repo.advance(action_id, WorkflowStatus.AWAITING_APPROVAL)
        ApprovalRepository(session).decide(action_id, "approved", reviewer_id="test")
        repo.advance(action_id, WorkflowStatus.READY)

    with pytest.raises(RuntimeError, match="rollback"), factory.begin() as session:
        WorkflowRepository(session).claim_ready(action_id)
        WorkflowOutboxRepository(session).enqueue_claimed(action_id)
        raise RuntimeError("rollback")

    with factory.begin() as session:
        assert WorkflowRepository(session).get(action_id).status == WorkflowStatus.READY
        assert session.get(WorkflowOutboxRow, action_id) is None


def test_outbox_claim_is_single_use_and_rechecks_approval(factory):
    action_id = uuid4()
    with factory.begin() as session:
        workflow = WorkflowRepository(session)
        workflow.create(WorkflowState(action_id=action_id, idempotency_key=str(uuid4())))
        workflow.advance(action_id, WorkflowStatus.AWAITING_APPROVAL)
        ApprovalRepository(session).decide(action_id, "approved", reviewer_id="test")
        workflow.advance(action_id, WorkflowStatus.READY)
        workflow.claim_ready(action_id)
        WorkflowOutboxRepository(session).enqueue_claimed(action_id)

    with factory.begin() as session:
        outbox = WorkflowOutboxRepository(session)
        claimed = outbox.claim_next_pending(action_id=action_id)
        assert claimed is not None
        assert claimed.action_id == action_id
        assert claimed.status == "claimed"
        assert outbox.claim_next_pending(action_id=action_id) is None


def test_outbox_quarantines_stale_workflow_before_dispatch(factory):
    action_id = uuid4()
    with factory.begin() as session:
        workflow = WorkflowRepository(session)
        workflow.create(WorkflowState(action_id=action_id, idempotency_key=str(uuid4())))
        workflow.advance(action_id, WorkflowStatus.AWAITING_APPROVAL)
        ApprovalRepository(session).decide(action_id, "approved", reviewer_id="test")
        workflow.advance(action_id, WorkflowStatus.READY)
        workflow.claim_ready(action_id)
        WorkflowOutboxRepository(session).enqueue_claimed(action_id)
        workflow.advance(action_id, WorkflowStatus.FAILED)

    with factory.begin() as session:
        assert WorkflowOutboxRepository(session).claim_next_pending(action_id=action_id) is None
        assert session.get(WorkflowOutboxRow, action_id).status == "quarantined"


def test_interrupted_outbox_claim_requires_explicit_quarantine(factory):
    action_id = uuid4()
    with factory.begin() as session:
        workflow = WorkflowRepository(session)
        workflow.create(WorkflowState(action_id=action_id, idempotency_key=str(uuid4())))
        workflow.advance(action_id, WorkflowStatus.AWAITING_APPROVAL)
        ApprovalRepository(session).decide(action_id, "approved", reviewer_id="test")
        workflow.advance(action_id, WorkflowStatus.READY)
        workflow.claim_ready(action_id)
        outbox = WorkflowOutboxRepository(session)
        outbox.enqueue_claimed(action_id)
        with pytest.raises(WorkflowTransitionError, match="Only claimed"):
            outbox.quarantine_interrupted_claim(action_id, reason="worker stopped")
        assert outbox.claim_next_pending(action_id=action_id) is not None

    with factory.begin() as session:
        outbox = WorkflowOutboxRepository(session)
        with pytest.raises(WorkflowTransitionError, match="reason"):
            outbox.quarantine_interrupted_claim(action_id, reason="  ")
        quarantined = outbox.quarantine_interrupted_claim(action_id, reason="worker stopped")
        assert quarantined.status == "quarantined"
        assert outbox.quarantine_interrupted_claim(action_id, reason="repeat").status == "quarantined"
        assert outbox.claim_next_pending(action_id=action_id) is None

    with factory.begin() as session:
        assert session.get(WorkflowOutboxRow, action_id).status == "quarantined"


def test_confirmed_dispatch_is_idempotent_and_cannot_replay(factory):
    action_id = uuid4()
    with factory.begin() as session:
        workflow = WorkflowRepository(session)
        workflow.create(WorkflowState(action_id=action_id, idempotency_key=str(uuid4())))
        workflow.advance(action_id, WorkflowStatus.AWAITING_APPROVAL)
        ApprovalRepository(session).decide(action_id, "approved", reviewer_id="test")
        workflow.advance(action_id, WorkflowStatus.READY)
        workflow.claim_ready(action_id)
        outbox = WorkflowOutboxRepository(session)
        outbox.enqueue_claimed(action_id)
        with pytest.raises(WorkflowTransitionError, match="Only claimed"):
            outbox.mark_dispatched(action_id)
        assert outbox.claim_next_pending(action_id=action_id) is not None
        assert outbox.mark_dispatched(action_id).status == "dispatched"
        assert outbox.mark_dispatched(action_id).status == "dispatched"
        assert outbox.claim_next_pending(action_id=action_id) is None

    with factory.begin() as session:
        assert session.get(WorkflowOutboxRow, action_id).status == "dispatched"
        with pytest.raises(WorkflowTransitionError, match="Only claimed"):
            WorkflowOutboxRepository(session).quarantine_interrupted_claim(
                action_id, reason="must not reopen completed dispatch"
            )


def test_quarantined_dispatch_cannot_be_marked_complete(factory):
    action_id = uuid4()
    with factory.begin() as session:
        workflow = WorkflowRepository(session)
        workflow.create(WorkflowState(action_id=action_id, idempotency_key=str(uuid4())))
        workflow.advance(action_id, WorkflowStatus.AWAITING_APPROVAL)
        ApprovalRepository(session).decide(action_id, "approved", reviewer_id="test")
        workflow.advance(action_id, WorkflowStatus.READY)
        workflow.claim_ready(action_id)
        outbox = WorkflowOutboxRepository(session)
        outbox.enqueue_claimed(action_id)
        outbox.claim_next_pending(action_id=action_id)
        outbox.quarantine_interrupted_claim(action_id, reason="unknown effect status")
        with pytest.raises(WorkflowTransitionError, match="Only claimed"):
            outbox.mark_dispatched(action_id)


def test_dispatch_confirmation_rechecks_persisted_approval(factory):
    action_id = uuid4()
    with factory.begin() as session:
        workflow = WorkflowRepository(session)
        workflow.create(WorkflowState(action_id=action_id, idempotency_key=str(uuid4())))
        workflow.advance(action_id, WorkflowStatus.AWAITING_APPROVAL)
        ApprovalRepository(session).decide(action_id, "approved", reviewer_id="test")
        workflow.advance(action_id, WorkflowStatus.READY)
        workflow.claim_ready(action_id)
        outbox = WorkflowOutboxRepository(session)
        outbox.enqueue_claimed(action_id)
        assert outbox.claim_next_pending(action_id=action_id) is not None

    # Simulate an out-of-band invalidation between claim and confirmation.
    # Terminal approval decisions are normally immutable through the repository.
    with factory.begin() as session:
        session.get(ApprovalRow, action_id).status = "rejected"

    with factory.begin() as session:
        outbox = WorkflowOutboxRepository(session)
        with pytest.raises(WorkflowTransitionError, match="approval changed"):
            outbox.mark_dispatched(action_id)
        assert session.get(WorkflowOutboxRow, action_id).status == "claimed"
