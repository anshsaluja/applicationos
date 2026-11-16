"""Regression coverage for persisted approval identity checks at outbox boundaries."""

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
    SyntheticReceiptRow,
    WorkflowOutboxRow,
    WorkflowOutboxRepository,
    WorkflowRepository,
    WorkflowRow,
)


@pytest.fixture(scope="module")
def factory():
    """Connect only to an explicitly configured disposable PostgreSQL test DB."""
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    if not url.startswith(("postgresql+psycopg://", "postgresql://")):
        pytest.fail("TEST_DATABASE_URL must point to PostgreSQL")
    engine = create_engine(url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


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
        assert session.get(WorkflowOutboxRow, action_id).status == "quarantined"


def test_dispatch_completion_rejects_corrupted_reviewer(factory):
    """A worker must recheck approval after claiming, before recording completion."""
    with factory.begin() as session:
        action_id = _running(session)
        outbox = WorkflowOutboxRepository(session)
        outbox.enqueue_claimed(action_id)
        assert outbox.claim_next_pending(action_id=action_id) is not None

    with factory.begin() as session:
        session.get(ApprovalRow, action_id).reviewer_id = "bad reviewer"

    with factory.begin() as session, pytest.raises(WorkflowTransitionError, match="approval changed"):
        WorkflowOutboxRepository(session).mark_dispatched(action_id, synthetic_receipt=True)

    with factory.begin() as session:
        assert session.get(WorkflowOutboxRow, action_id).status == "claimed"
        assert session.get(SyntheticReceiptRow, action_id) is None


@pytest.mark.parametrize(
    ("attempt", "max_attempts"),
    [(0, 2), (-1, 2), (1, 0), (3, 2)],
)
def test_dispatch_completion_rejects_corrupted_retry_budget(factory, attempt, max_attempts):
    """A claimed outbox row cannot confirm a corrupted execution checkpoint."""
    with factory.begin() as session:
        action_id = _running(session)
        outbox = WorkflowOutboxRepository(session)
        outbox.enqueue_claimed(action_id)
        assert outbox.claim_next_pending(action_id=action_id) is not None

    with factory.begin() as session:
        workflow = session.get(WorkflowRow, action_id)
        workflow.attempt = attempt
        workflow.max_attempts = max_attempts

    with factory.begin() as session, pytest.raises(
        WorkflowTransitionError, match="checkpoint or approval changed"
    ):
        WorkflowOutboxRepository(session).mark_dispatched(action_id, synthetic_receipt=True)

    with factory.begin() as session:
        assert session.get(WorkflowOutboxRow, action_id).status == "claimed"
        assert session.get(SyntheticReceiptRow, action_id) is None
