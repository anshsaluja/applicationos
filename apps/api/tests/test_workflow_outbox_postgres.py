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

    with pytest.raises(RuntimeError, match="rollback"):
        with factory.begin() as session:
            WorkflowRepository(session).claim_ready(action_id)
            WorkflowOutboxRepository(session).enqueue_claimed(action_id)
            raise RuntimeError("rollback")

    with factory.begin() as session:
        assert WorkflowRepository(session).get(action_id).status == WorkflowStatus.READY
        assert session.get(WorkflowOutboxRow, action_id) is None
