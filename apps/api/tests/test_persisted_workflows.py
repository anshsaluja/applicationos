"""PostgreSQL integration coverage for durable, fail-closed workflow checkpoints."""
from uuid import uuid4

import pytest

from app.domain.approvals import ApprovalStatus
from app.domain.workflows import WorkflowState, WorkflowStatus, WorkflowTransitionError
from app.persistence import (
    ApprovalRepository,
    WorkflowRepository,
    build_session_factory,
    session_scope,
)


def test_checkpoint_survives_sessions_and_requires_persisted_approval():
    factory = build_session_factory()
    action_id = uuid4()
    initial = WorkflowState(action_id=action_id, idempotency_key=f"test:{action_id}")
    with session_scope(factory) as session:
        repo = WorkflowRepository(session)
        assert repo.create(initial) == initial
        assert repo.create(initial) == initial
        repo.advance(action_id, WorkflowStatus.AWAITING_APPROVAL)
        with pytest.raises(WorkflowTransitionError, match="approval"):
            repo.advance(action_id, WorkflowStatus.READY)

    with session_scope(factory) as session:
        repo = WorkflowRepository(session)
        assert repo.get(action_id).status == WorkflowStatus.AWAITING_APPROVAL
        ApprovalRepository(session).decide(
            action_id, ApprovalStatus.APPROVED, reviewer_id="test-reviewer"
        )
        assert repo.advance(action_id, WorkflowStatus.READY).status == WorkflowStatus.READY

    with session_scope(factory) as session:
        repo = WorkflowRepository(session)
        running = repo.advance(action_id, WorkflowStatus.RUNNING)
        assert running.attempt == 1
        assert repo.advance(action_id, WorkflowStatus.SUCCEEDED).status == WorkflowStatus.SUCCEEDED

    with session_scope(factory) as session:
        repo = WorkflowRepository(session)
        assert repo.get(action_id).status == WorkflowStatus.SUCCEEDED
        with pytest.raises(WorkflowTransitionError, match="Invalid transition"):
            repo.advance(action_id, WorkflowStatus.RUNNING)


def test_idempotency_key_cannot_be_reused_by_another_action():
    factory = build_session_factory()
    key = f"unique:{uuid4()}"
    with session_scope(factory) as session:
        WorkflowRepository(session).create(WorkflowState(action_id=uuid4(), idempotency_key=key))
    with session_scope(factory) as session, pytest.raises(
        WorkflowTransitionError, match="Idempotency key"
    ):
        WorkflowRepository(session).create(WorkflowState(action_id=uuid4(), idempotency_key=key))


def test_retry_checkpoint_retains_error_and_attempt_count():
    factory = build_session_factory()
    action_id = uuid4()
    with session_scope(factory) as session:
        repo = WorkflowRepository(session)
        repo.create(WorkflowState(action_id=action_id, idempotency_key=f"retry:{action_id}", max_attempts=1))
        repo.advance(action_id, WorkflowStatus.AWAITING_APPROVAL)
        ApprovalRepository(session).decide(action_id, ApprovalStatus.APPROVED, reviewer_id="reviewer")
        repo.advance(action_id, WorkflowStatus.READY)
        repo.advance(action_id, WorkflowStatus.RUNNING)
        failed = repo.advance(action_id, WorkflowStatus.FAILED, error="synthetic failure")
        assert failed.attempt == 1
        assert failed.last_error == "synthetic failure"

    with session_scope(factory) as session:
        repo = WorkflowRepository(session)
        assert repo.get(action_id).last_error == "synthetic failure"
        with pytest.raises(WorkflowTransitionError, match="budget"):
            repo.advance(action_id, WorkflowStatus.READY)


def test_interrupted_running_workflow_is_recoverable_without_replaying():
    factory = build_session_factory()
    action_id = uuid4()
    with session_scope(factory) as session:
        repo = WorkflowRepository(session)
        repo.create(WorkflowState(action_id=action_id, idempotency_key=f"recover:{action_id}"))
        repo.advance(action_id, WorkflowStatus.AWAITING_APPROVAL)
        ApprovalRepository(session).decide(action_id, ApprovalStatus.APPROVED, reviewer_id="reviewer")
        repo.advance(action_id, WorkflowStatus.READY)
        assert repo.advance(action_id, WorkflowStatus.RUNNING).attempt == 1

    # Simulate the original worker stopping and a new process recovering state.
    with session_scope(factory) as session:
        repo = WorkflowRepository(session)
        failed = repo.recover_interrupted(action_id, reason="worker exited")
        assert failed.status == WorkflowStatus.FAILED
        assert failed.attempt == 1
        assert failed.last_error == "worker exited"
        assert repo.recover_interrupted(action_id, reason="duplicate recovery") == failed
        assert repo.advance(action_id, WorkflowStatus.READY).status == WorkflowStatus.READY
        assert repo.advance(action_id, WorkflowStatus.RUNNING).attempt == 2


def test_recovery_rejects_non_running_workflows_and_empty_reason():
    factory = build_session_factory()
    action_id = uuid4()
    with session_scope(factory) as session:
        repo = WorkflowRepository(session)
        repo.create(WorkflowState(action_id=action_id, idempotency_key=f"not-running:{action_id}"))
        with pytest.raises(WorkflowTransitionError, match="Only running"):
            repo.recover_interrupted(action_id)
        with pytest.raises(WorkflowTransitionError, match="reason"):
            repo.recover_interrupted(action_id, reason="  ")
        with pytest.raises(WorkflowTransitionError, match="not found"):
            repo.recover_interrupted(uuid4())
