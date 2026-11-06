"""PostgreSQL integration coverage for locked workflow claiming.

Run against a disposable database only:
    TEST_DATABASE_URL=postgresql+psycopg://... pytest -q tests/test_claim_ready_postgres.py
Never point TEST_DATABASE_URL at production or a shared development database.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain.workflows import WorkflowState, WorkflowStatus, WorkflowTransitionError
from app.persistence import Base, ApprovalRepository, WorkflowRepository


@pytest.fixture(scope="module")
def factory():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    if not url.startswith(("postgresql+psycopg://", "postgresql://")):
        pytest.fail("TEST_DATABASE_URL must point to PostgreSQL")
    engine = create_engine(url, pool_pre_ping=True)
    # Only use a disposable test database: this creates tables, never drops them.
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def new_workflow(factory, *, approve=True, max_attempts=2):
    action_id = uuid4()
    with factory.begin() as session:
        repo = WorkflowRepository(session)
        repo.create(WorkflowState(action_id=action_id, idempotency_key=str(uuid4()), max_attempts=max_attempts))
        repo.advance(action_id, WorkflowStatus.AWAITING_APPROVAL)
        if approve:
            ApprovalRepository(session).decide(action_id, "approved", reviewer_id="integration-test")
            repo.advance(action_id, WorkflowStatus.READY)
    return action_id


def test_claim_requires_durable_approval(factory):
    action_id = new_workflow(factory, approve=False)
    with factory.begin() as session:
        with pytest.raises(WorkflowTransitionError):
            WorkflowRepository(session).claim_ready(action_id)


def test_claim_is_single_winner_across_sessions(factory):
    action_id = new_workflow(factory)

    def claim():
        with factory.begin() as session:
            try:
                return WorkflowRepository(session).claim_ready(action_id).attempt
            except WorkflowTransitionError:
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: claim(), range(2)))
    assert sorted(outcomes, key=lambda value: value is None) == [1, None]
    with factory.begin() as session:
        state = WorkflowRepository(session).get(action_id)
        assert state.status == WorkflowStatus.RUNNING
        assert state.attempt == 1


def test_retry_budget_and_recovery_are_durable(factory):
    action_id = new_workflow(factory, max_attempts=1)
    with factory.begin() as session:
        repo = WorkflowRepository(session)
        assert repo.claim_ready(action_id).attempt == 1
    with factory.begin() as session:
        repo = WorkflowRepository(session)
        recovered = repo.recover_interrupted(action_id)
        assert recovered.status == WorkflowStatus.FAILED
        assert repo.recover_interrupted(action_id).attempt == 1
        with pytest.raises(WorkflowTransitionError, match="Retry budget exhausted"):
            repo.advance(action_id, WorkflowStatus.READY)


def test_batch_claim_skips_locked_rows_and_claims_distinct_work(factory):
    """A busy worker must not prevent another worker claiming a different action."""
    from threading import Event

    first = new_workflow(factory)
    second = new_workflow(factory)
    ordered = sorted((first, second))
    locked = Event()
    release = Event()

    def hold_first_row_lock():
        with factory.begin() as session:
            from app.persistence import WorkflowRow

            session.query(WorkflowRow).filter_by(action_id=ordered[0]).with_for_update().one()
            locked.set()
            assert release.wait(timeout=10), "Timed out waiting to release row lock"

    with ThreadPoolExecutor(max_workers=2) as pool:
        holder = pool.submit(hold_first_row_lock)
        try:
            assert locked.wait(timeout=10), "Timed out acquiring row lock"
            with factory.begin() as session:
                claimed = WorkflowRepository(session).claim_next_ready()
                assert claimed is not None
                assert claimed.action_id == ordered[1]
                assert claimed.status == WorkflowStatus.RUNNING
                assert claimed.attempt == 1
        finally:
            release.set()
            holder.result(timeout=10)

    with factory.begin() as session:
        claimed = WorkflowRepository(session).claim_next_ready()
        assert claimed is not None
        assert claimed.action_id == ordered[0]
        assert claimed.attempt == 1

    with factory.begin() as session:
        repo = WorkflowRepository(session)
        assert repo.get(ordered[0]).status == WorkflowStatus.RUNNING
        assert repo.get(ordered[1]).status == WorkflowStatus.RUNNING
