"""Approval audit reasons must not conceal decisions or flood reviewer interfaces."""
from uuid import uuid4

import pytest

from app.domain.approvals import (
    ApprovalDecision,
    ApprovalGateError,
    ApprovalStatus,
    decide,
    require_approved,
)


@pytest.mark.parametrize("reason", [
    "Looks fine\u202eDENIED",
    "Approved\u200b silently",
    "Review\x00complete",
    "A" * 2001,
])
def test_reject_unsafe_approval_reasons(reason):
    pending = ApprovalDecision(action_id=uuid4())
    with pytest.raises(ApprovalGateError, match="Invalid approval reason"):
        decide(pending, ApprovalStatus.APPROVED, reviewer_id="reviewer-1", reason=reason)


def test_accept_normal_multiline_reason_and_preserve_idempotency():
    pending = ApprovalDecision(action_id=uuid4())
    reason = "Checked evidence:\n\t- identity verified"
    approved = decide(pending, ApprovalStatus.APPROVED, reviewer_id="reviewer-1", reason=reason)
    assert approved.reason == reason
    assert decide(approved, ApprovalStatus.APPROVED, reviewer_id="reviewer-1", reason=reason) == approved


def test_rejection_still_requires_nonblank_reason():
    with pytest.raises(ApprovalGateError, match="Rejection requires a reason"):
        decide(ApprovalDecision(action_id=uuid4()), ApprovalStatus.REJECTED, reviewer_id="reviewer-1", reason="  ")


@pytest.mark.parametrize("unsafe_reason", [
    "Approved\u202eDENIED",
    "Hidden\u200btext",
    "Control\x00byte",
    "A" * 2001,
])
def test_persisted_unsafe_approval_reason_fails_closed(unsafe_reason):
    """A corrupt or legacy persisted approval cannot authorize execution."""
    action_id = uuid4()
    persisted = ApprovalDecision(
        action_id=action_id,
        status=ApprovalStatus.APPROVED,
        reviewer_id="reviewer-1",
        reason=unsafe_reason,
    )
    with pytest.raises(ApprovalGateError, match="Action has not been approved"):
        require_approved(persisted, action_id)


def test_persisted_safe_approval_reason_still_authorizes():
    action_id = uuid4()
    persisted = ApprovalDecision(
        action_id=action_id,
        status=ApprovalStatus.APPROVED,
        reviewer_id="reviewer-1",
        reason="Evidence reviewed",
    )
    require_approved(persisted, action_id)


@pytest.mark.parametrize(
    ("reviewer_id", "reason"),
    [
        ("reviewer-1", "Hidden\u200btext"),
        ("reviewer-1", "A" * 2001),
        ("reviewer\u202e-1", "Evidence reviewed"),
        ("reviewer 1", "Evidence reviewed"),
    ],
)
def test_replay_rejects_corrupt_persisted_approval(reviewer_id, reason):
    """A matching replay must not bless an invalid persisted audit record."""
    persisted = ApprovalDecision(
        action_id=uuid4(),
        status=ApprovalStatus.APPROVED,
        reviewer_id=reviewer_id,
        reason=reason,
    )
    with pytest.raises(ApprovalGateError, match="Persisted approval decision is invalid"):
        decide(
            persisted,
            ApprovalStatus.APPROVED,
            reviewer_id="reviewer-1",
            reason=reason,
        )
