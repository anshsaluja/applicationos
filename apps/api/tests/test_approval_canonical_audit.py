"""Persisted approval audit reasons must be canonical before authorization."""

from uuid import uuid4

import pytest

from app.domain.approvals import (
    ApprovalDecision,
    ApprovalGateError,
    ApprovalStatus,
    decide,
    require_approved,
)


@pytest.mark.parametrize("reason", [" approved", "approved ", "\tapproved", "approved\n"])
def test_noncanonical_persisted_approval_cannot_authorize(reason: str) -> None:
    action_id = uuid4()
    persisted = ApprovalDecision(
        action_id=action_id,
        status=ApprovalStatus.APPROVED,
        reviewer_id="reviewer-42",
        reason=reason,
    )
    with pytest.raises(ApprovalGateError, match="not been approved"):
        require_approved(persisted, action_id)
    with pytest.raises(ApprovalGateError, match="Persisted approval decision is invalid"):
        decide(
            persisted,
            ApprovalStatus.APPROVED,
            reviewer_id="reviewer-42",
            reason=reason,
        )


def test_new_decision_normalizes_reason_and_allows_idempotent_replay() -> None:
    action_id = uuid4()
    approved = decide(
        ApprovalDecision(action_id=action_id),
        ApprovalStatus.APPROVED,
        reviewer_id="reviewer-42",
        reason="  reviewed evidence  ",
    )
    assert approved.reason == "reviewed evidence"
    require_approved(approved, action_id)
    assert decide(
        approved,
        ApprovalStatus.APPROVED,
        reviewer_id="reviewer-42",
        reason=" reviewed evidence ",
    ) == approved
