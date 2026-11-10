"""Receipt-aware outbox claiming regression tests.

These exercise the repository claim path with an isolated in-memory database.
PostgreSQL concurrency and Docker end-to-end behavior require separate checks.
"""
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.persistence import (
    ApprovalRow,
    Base,
    SyntheticReceiptRow,
    WorkflowOutboxRepository,
    WorkflowOutboxRow,
    WorkflowRow,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def seed(session, *, receipt=False, approval="approved", status="running"):
    action_id = uuid4()
    key = f"test:{action_id}"
    session.add(
        WorkflowRow(
            action_id=action_id,
            idempotency_key=key,
            status=status,
            attempt=1,
            max_attempts=3,
            last_error=None,
        )
    )
    session.add(
        ApprovalRow(
            action_id=action_id,
            status=approval,
            reviewer_id="test-operator",
            reason=None,
            decided_at=datetime.now(UTC),
        )
    )
    session.add(
        WorkflowOutboxRow(
            action_id=action_id,
            idempotency_key=key,
            status="pending",
            created_at=datetime.now(UTC),
        )
    )
    if receipt:
        session.add(
            SyntheticReceiptRow(
                action_id=action_id,
                idempotency_key=key,
                adapter="synthetic-noop",
                recorded_at=datetime.now(UTC),
            )
        )
    session.flush()
    return action_id


@pytest.mark.parametrize("receipt", [False, True])
def test_pending_intent_claim_respects_existing_receipt(session, receipt):
    action_id = seed(session, receipt=receipt)
    claimed = WorkflowOutboxRepository(session).claim_next_pending(action_id=action_id)
    row = session.get(WorkflowOutboxRow, action_id)
    if receipt:
        assert claimed is None
        assert row.status == "quarantined"
        # Quarantined intents cannot be reclaimed by a later worker.
        assert WorkflowOutboxRepository(session).claim_next_pending(action_id=action_id) is None
    else:
        assert claimed is not None
        assert row.status == "claimed"


def test_invalid_receipt_quarantines_and_does_not_starve_valid_intent(session):
    unsafe = seed(session, receipt=True)
    safe = seed(session)
    receipt = session.get(SyntheticReceiptRow, unsafe)
    receipt.idempotency_key = "mismatched-key"
    session.flush()

    claimed = WorkflowOutboxRepository(session).claim_next_pending()
    assert claimed is not None
    assert claimed.action_id == safe
    assert session.get(WorkflowOutboxRow, unsafe).status == "quarantined"
    assert session.get(WorkflowOutboxRow, safe).status == "claimed"


@pytest.mark.parametrize(
    ("approval", "status"),
    [("rejected", "running"), ("approved", "failed")],
)
def test_claim_quarantines_stale_authorization(session, approval, status):
    action_id = seed(session, approval=approval, status=status)
    assert WorkflowOutboxRepository(session).claim_next_pending(action_id=action_id) is None
    assert session.get(WorkflowOutboxRow, action_id).status == "quarantined"
