"""PostgreSQL integration tests for durable approval decisions."""
from uuid import uuid4

import pytest

from app.domain.approvals import ApprovalGateError, ApprovalStatus, require_approved
from app.persistence import ApprovalRepository, build_session_factory, session_scope


def test_approval_persists_across_sessions_and_is_idempotent():
    action_id = uuid4()
    factory = build_session_factory()
    with session_scope(factory) as session:
        approval = ApprovalRepository(session).decide(
            action_id, ApprovalStatus.APPROVED, reviewer_id="reviewer-1"
        )
        require_approved(approval, action_id)
    with session_scope(factory) as session:
        repository = ApprovalRepository(session)
        assert repository.get(action_id) == approval
        assert repository.decide(
            action_id, ApprovalStatus.APPROVED, reviewer_id="reviewer-1"
        ) == approval


def test_rejection_is_durable_and_cannot_be_overridden():
    action_id = uuid4()
    factory = build_session_factory()
    with session_scope(factory) as session:
        ApprovalRepository(session).decide(
            action_id, ApprovalStatus.REJECTED,
            reviewer_id="reviewer-2", reason="Missing proof",
        )
    with pytest.raises(ApprovalGateError), session_scope(factory) as session:
        ApprovalRepository(session).decide(
            action_id, ApprovalStatus.APPROVED, reviewer_id="reviewer-3"
        )
    with session_scope(factory) as session:
        decision = ApprovalRepository(session).get(action_id)
        assert decision.status == ApprovalStatus.REJECTED
        with pytest.raises(ApprovalGateError):
            require_approved(decision, action_id)


def test_missing_decision_fails_closed():
    factory = build_session_factory()
    action_id = uuid4()
    with session_scope(factory) as session:
        decision = ApprovalRepository(session).get(action_id)
        assert decision.status == ApprovalStatus.PENDING
        with pytest.raises(ApprovalGateError):
            require_approved(decision, action_id)
