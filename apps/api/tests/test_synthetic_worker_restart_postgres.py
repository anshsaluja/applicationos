"""PostgreSQL integration checks for the synthetic worker's transaction boundary.

The adapter has no external side effects. These tests require DATABASE_URL to
point to a disposable PostgreSQL database initialized by the test/CI setup.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from app.domain.approvals import ApprovalStatus
from app.domain.workflows import WorkflowState, WorkflowStatus
from app.persistence import (
    ApprovalRepository,
    SyntheticReceiptRow,
    WorkflowOutboxRepository,
    WorkflowOutboxRow,
    WorkflowRepository,
    build_session_factory,
    session_scope,
)
from app.synthetic_worker import dispatch_one_synthetic


@pytest.fixture(autouse=True)
def require_disposable_postgres():
    """Never write integration fixtures to an implicit or remote database."""
    database_url = os.getenv("DATABASE_URL", "")
    test_url = os.getenv("TEST_DATABASE_URL", "")
    if not test_url:
        pytest.skip("TEST_DATABASE_URL must explicitly identify a disposable database")
    if database_url != test_url:
        pytest.fail("DATABASE_URL must match the explicitly configured TEST_DATABASE_URL")
    parsed = urlsplit(test_url)
    if not parsed.scheme.startswith("postgresql") or parsed.hostname not in {
        "localhost", "127.0.0.1", "postgres"
    }:
        pytest.fail("Synthetic worker integration tests require local PostgreSQL")


def prepare_approved_dispatch(factory):
    action_id = uuid4()
    key = f"synthetic-integration:{action_id}"
    with session_scope(factory) as session:
        workflows = WorkflowRepository(session)
        workflows.create(WorkflowState(action_id=action_id, idempotency_key=key))
        workflows.advance(action_id, WorkflowStatus.AWAITING_APPROVAL)
        ApprovalRepository(session).decide(
            action_id, ApprovalStatus.APPROVED, reviewer_id="synthetic-test"
        )
        workflows.advance(action_id, WorkflowStatus.READY)
        workflows.claim_ready(action_id)
        WorkflowOutboxRepository(session).enqueue_claimed(action_id)
    return action_id, key


def test_synthetic_dispatch_persists_receipt_and_does_not_repeat():
    factory = build_session_factory()
    action_id, key = prepare_approved_dispatch(factory)

    receipt = dispatch_one_synthetic(factory, action_id=action_id)
    assert receipt is not None
    assert receipt.action_id == action_id
    assert receipt.idempotency_key == key

    # A new session simulates a process restart: all evidence must be durable.
    with session_scope(factory) as session:
        assert WorkflowRepository(session).get(action_id).status == WorkflowStatus.SUCCEEDED
        assert session.get(WorkflowOutboxRow, action_id).status == "dispatched"
        persisted = session.get(SyntheticReceiptRow, action_id)
        assert persisted is not None
        assert persisted.idempotency_key == key
        assert persisted.adapter == "synthetic-noop"

    assert dispatch_one_synthetic(factory, action_id=action_id) is None


def test_crash_after_claim_cannot_silently_replay_synthetic_action():
    factory = build_session_factory()
    action_id, _ = prepare_approved_dispatch(factory)

    # Simulate the worker committing the claim and terminating before ack.
    with session_scope(factory) as session:
        claimed = WorkflowOutboxRepository(session).claim_next_pending(action_id=action_id)
        assert claimed is not None
        assert claimed.status == "claimed"

    assert dispatch_one_synthetic(factory, action_id=action_id) is None
    with session_scope(factory) as session:
        assert session.get(WorkflowOutboxRow, action_id).status == "claimed"
        assert session.get(SyntheticReceiptRow, action_id) is None
        assert WorkflowRepository(session).get(action_id).status == WorkflowStatus.RUNNING

    with session_scope(factory) as session:
        recovered = WorkflowRepository(session).recover_interrupted(
            action_id, reason="simulated worker crash"
        )
        assert recovered.status == WorkflowStatus.FAILED
        assert session.get(WorkflowOutboxRow, action_id).status == "quarantined"

    assert dispatch_one_synthetic(factory, action_id=action_id) is None


def test_concurrent_synthetic_workers_dispatch_once():
    """Two workers racing on one outbox row must produce one durable receipt."""
    factory = build_session_factory()
    action_id, key = prepare_approved_dispatch(factory)
    barrier = Barrier(2)

    def run_worker():
        barrier.wait(timeout=10)
        return dispatch_one_synthetic(factory, action_id=action_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run_worker) for _ in range(2)]
        receipts = [future.result(timeout=20) for future in futures]

    winners = [receipt for receipt in receipts if receipt is not None]
    assert len(winners) == 1
    assert winners[0].action_id == action_id
    assert winners[0].idempotency_key == key

    with session_scope(factory) as session:
        assert WorkflowRepository(session).get(action_id).status == WorkflowStatus.SUCCEEDED
        assert session.get(WorkflowOutboxRow, action_id).status == "dispatched"
        persisted = session.get(SyntheticReceiptRow, action_id)
        assert persisted is not None
        assert persisted.idempotency_key == key

    assert dispatch_one_synthetic(factory, action_id=action_id) is None


def test_dispatching_one_action_does_not_consume_another_actions_outbox():
    """Dispatching one action must not acknowledge another tenant's pending work."""
    factory = build_session_factory()
    first_id, first_key = prepare_approved_dispatch(factory)
    second_id, second_key = prepare_approved_dispatch(factory)

    first_receipt = dispatch_one_synthetic(factory, action_id=first_id)
    assert first_receipt is not None
    assert first_receipt.idempotency_key == first_key

    with session_scope(factory) as session:
        assert session.get(WorkflowOutboxRow, first_id).status == "dispatched"
        assert session.get(WorkflowOutboxRow, second_id).status == "pending"
        assert session.get(SyntheticReceiptRow, second_id) is None
        assert WorkflowRepository(session).get(second_id).status == WorkflowStatus.RUNNING

    second_receipt = dispatch_one_synthetic(factory, action_id=second_id)
    assert second_receipt is not None
    assert second_receipt.idempotency_key == second_key
    assert second_receipt.action_id != first_receipt.action_id

    with session_scope(factory) as session:
        assert session.get(WorkflowOutboxRow, second_id).status == "dispatched"
        assert WorkflowRepository(session).get(second_id).status == WorkflowStatus.SUCCEEDED
        assert session.get(SyntheticReceiptRow, first_id).idempotency_key == first_key
        assert session.get(SyntheticReceiptRow, second_id).idempotency_key == second_key

    assert dispatch_one_synthetic(factory, action_id=first_id) is None
    assert dispatch_one_synthetic(factory, action_id=second_id) is None

def test_quarantined_crashed_action_does_not_block_independent_dispatch():
    """Recovery must isolate an interrupted action without losing other pending work."""
    factory = build_session_factory()
    crashed_id, _ = prepare_approved_dispatch(factory)
    healthy_id, healthy_key = prepare_approved_dispatch(factory)

    with session_scope(factory) as session:
        claimed = WorkflowOutboxRepository(session).claim_next_pending(action_id=crashed_id)
        assert claimed is not None
        assert claimed.status == "claimed"

    with session_scope(factory) as session:
        recovered = WorkflowRepository(session).recover_interrupted(
            crashed_id, reason="synthetic crash isolation test"
        )
        assert recovered.status == WorkflowStatus.FAILED
        assert session.get(WorkflowOutboxRow, crashed_id).status == "quarantined"
        assert session.get(WorkflowOutboxRow, healthy_id).status == "pending"

    assert dispatch_one_synthetic(factory, action_id=crashed_id) is None
    receipt = dispatch_one_synthetic(factory, action_id=healthy_id)
    assert receipt is not None
    assert receipt.idempotency_key == healthy_key

    with session_scope(factory) as session:
        assert session.get(SyntheticReceiptRow, crashed_id) is None
        assert session.get(WorkflowOutboxRow, crashed_id).status == "quarantined"
        assert WorkflowRepository(session).get(crashed_id).status == WorkflowStatus.FAILED
        assert session.get(SyntheticReceiptRow, healthy_id) is not None
        assert WorkflowRepository(session).get(healthy_id).status == WorkflowStatus.SUCCEEDED

    assert dispatch_one_synthetic(factory, action_id=healthy_id) is None



def test_synthetic_receipt_survives_new_session_factory_and_cannot_replay():
    """Reconstruct the DB connection after completion to simulate worker restart."""
    first_factory = build_session_factory()
    action_id, key = prepare_approved_dispatch(first_factory)
    receipt = dispatch_one_synthetic(first_factory, action_id=action_id)
    assert receipt is not None
    assert receipt.idempotency_key == key

    # A fresh factory cannot depend on process-local workflow or receipt caches.
    restarted_factory = build_session_factory()
    with session_scope(restarted_factory) as session:
        checkpoint = WorkflowRepository(session).get(action_id)
        assert checkpoint.status == WorkflowStatus.SUCCEEDED
        assert checkpoint.idempotency_key == key
        assert session.get(WorkflowOutboxRow, action_id).status == "dispatched"
        persisted = session.get(SyntheticReceiptRow, action_id)
        assert persisted is not None
        assert persisted.idempotency_key == key
        assert persisted.adapter == "synthetic-noop"

    assert dispatch_one_synthetic(restarted_factory, action_id=action_id) is None
    with session_scope(restarted_factory) as session:
        assert session.get(SyntheticReceiptRow, action_id).idempotency_key == key
