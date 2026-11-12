"""Approval replay and identity-boundary regressions.

These fast domain checks complement PostgreSQL and Playwright tests; they do not
claim to prove database concurrency or restart recovery.
"""

from uuid import uuid4

import pytest

from app.domain.approvals import (
    ApprovalDecision,
    ApprovalGateError,
    ApprovalStatus,
    decide,
    require_approved,
)


@pytest.mark.parametrize("status", [ApprovalStatus.APPROVED, ApprovalStatus.REJECTED])
def test_identical_terminal_decision_is_idempotent(status: ApprovalStatus) -> None:
    pending = ApprovalDecision(action_id=uuid4())
    reason = "Missing evidence" if status == ApprovalStatus.REJECTED else None
    first = decide(pending, status, reviewer_id="  reviewer-1  ", reason=reason)
    replay = decide(first, status, reviewer_id="reviewer-1", reason=reason)
    assert replay == first
    assert replay.reviewer_id == "reviewer-1"
    assert pending.status == ApprovalStatus.PENDING


@pytest.mark.parametrize("status", [ApprovalStatus.APPROVED, ApprovalStatus.REJECTED])
def test_terminal_decision_rejects_different_reviewer(status: ApprovalStatus) -> None:
    pending = ApprovalDecision(action_id=uuid4())
    reason = "Missing evidence" if status == ApprovalStatus.REJECTED else None
    first = decide(pending, status, reviewer_id="reviewer-1", reason=reason)
    with pytest.raises(ApprovalGateError, match="final"):
        decide(first, status, reviewer_id="reviewer-2", reason=reason)


def test_rejected_decision_cannot_be_replayed_with_changed_reason() -> None:
    pending = ApprovalDecision(action_id=uuid4())
    first = decide(
        pending, ApprovalStatus.REJECTED,
        reviewer_id="reviewer-1", reason="Missing evidence",
    )
    with pytest.raises(ApprovalGateError, match="final"):
        decide(
            first, ApprovalStatus.REJECTED,
            reviewer_id="reviewer-1", reason="Different rationale",
        )


@pytest.mark.parametrize("status", [ApprovalStatus.PENDING, ApprovalStatus.REJECTED])
def test_unapproved_decision_fails_closed(status: ApprovalStatus) -> None:
    action_id = uuid4()
    decision = ApprovalDecision(
        action_id=action_id,
        status=status,
        reviewer_id="reviewer-1",
        reason="Missing evidence" if status == ApprovalStatus.REJECTED else None,
    )
    with pytest.raises(ApprovalGateError, match="not been approved"):
        require_approved(decision, action_id)


def test_blank_reviewer_never_authorizes_approved_action() -> None:
    action_id = uuid4()
    forged = ApprovalDecision(
        action_id=action_id,
        status=ApprovalStatus.APPROVED,
        reviewer_id=" \t ",
    )
    with pytest.raises(ApprovalGateError, match="not been approved"):
        require_approved(forged, action_id)
