"""PostgreSQL integration coverage for the local synthetic outbox consumer."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain.workflows import WorkflowState, WorkflowStatus
from app.persistence import (
    ApprovalRepository,
    Base,
    SyntheticReceiptRow,
    WorkflowOutboxRepository,
    WorkflowRow,
    WorkflowOutboxRow,
    WorkflowRepository,
)
from app.synthetic_worker import dispatch_one_synthetic


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


def test_synthetic_dispatch_requires_approval_and_is_single_use(factory):
    action_id = uuid4()
    with factory.begin() as session:
        workflow = WorkflowRepository(session)
        workflow.create(WorkflowState(action_id=action_id, idempotency_key=str(uuid4())))
        workflow.advance(action_id, WorkflowStatus.AWAITING_APPROVAL)
        ApprovalRepository(session).decide(action_id, "approved", reviewer_id="test")
        workflow.advance(action_id, WorkflowStatus.READY)
        workflow.claim_ready(action_id)
        WorkflowOutboxRepository(session).enqueue_claimed(action_id)

    receipt = dispatch_one_synthetic(factory, action_id=action_id)
    assert receipt is not None
    assert receipt.action_id == action_id
    assert receipt.adapter == "synthetic-noop"
    assert dispatch_one_synthetic(factory, action_id=action_id) is None
    with factory.begin() as session:
        row = session.get(WorkflowOutboxRow, action_id)
        assert row.status == "dispatched"
        assert session.get(WorkflowRow, action_id).status == WorkflowStatus.SUCCEEDED.value
        assert row.idempotency_key == receipt.idempotency_key
        durable = session.get(SyntheticReceiptRow, action_id)
        assert durable is not None
        assert durable.idempotency_key == receipt.idempotency_key
        assert durable.adapter == "synthetic-noop"


def test_synthetic_worker_does_not_claim_unapproved_intent(factory):
    action_id = uuid4()
    with factory.begin() as session:
        workflow = WorkflowRepository(session)
        workflow.create(WorkflowState(action_id=action_id, idempotency_key=str(uuid4())))
        workflow.advance(action_id, WorkflowStatus.AWAITING_APPROVAL)
        ApprovalRepository(session).decide(action_id, "approved", reviewer_id="test")
        workflow.advance(action_id, WorkflowStatus.READY)
        workflow.claim_ready(action_id)
        WorkflowOutboxRepository(session).enqueue_claimed(action_id)

    # Approval is invalidated after enqueue, before the worker claims it.
    with factory.begin() as session:
        from app.persistence import ApprovalRow

        session.get(ApprovalRow, action_id).status = "rejected"

    assert dispatch_one_synthetic(factory, action_id=action_id) is None
    with factory.begin() as session:
        assert session.get(WorkflowOutboxRow, action_id).status == "quarantined"
        assert session.get(SyntheticReceiptRow, action_id) is None


def test_synthetic_completion_requires_matching_receipt(factory):
    from app.domain.workflows import WorkflowTransitionError

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
        with pytest.raises(WorkflowTransitionError, match="receipt"):
            outbox.complete_synthetic(action_id)
        assert session.get(WorkflowRow, action_id).status == WorkflowStatus.RUNNING.value

    assert dispatch_one_synthetic(factory, action_id=action_id) is not None
    with factory.begin() as session:
        outbox = WorkflowOutboxRepository(session)
        assert outbox.complete_synthetic(action_id).status == WorkflowStatus.SUCCEEDED.value
