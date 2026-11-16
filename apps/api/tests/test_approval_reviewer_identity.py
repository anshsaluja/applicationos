"""Fail-closed reviewer identity checks at creation and durable replay boundaries."""

from uuid import uuid4

import pytest

from app.domain.approvals import (
    ApprovalDecision,
    ApprovalGateError,
    ApprovalStatus,
    decide,
    require_approved,
)


@pytest.mark.parametrize(
    "reviewer",
    ["", " ", " reviewer", "reviewer ", "review er", "review\tuser",
     "review\nuser", "review\u200buser", "review\u202euser",
     "review\x00user", "review\ud800user", "review\u0378user"],
)
def test_rejects_ambiguous_reviewer_at_decision_and_replay(reviewer: str) -> None:
    action_id = uuid4()
    pending = ApprovalDecision(action_id=action_id)
    with pytest.raises(ApprovalGateError, match="reviewer"):
        decide(pending, ApprovalStatus.APPROVED, reviewer_id=reviewer)
    persisted = ApprovalDecision(
        action_id=action_id, status=ApprovalStatus.APPROVED, reviewer_id=reviewer
    )
    with pytest.raises(ApprovalGateError, match="approved"):
        require_approved(persisted, action_id)


def test_visible_unicode_reviewer_still_authorizes_matching_action() -> None:
    action_id = uuid4()
    approved = decide(
        ApprovalDecision(action_id=action_id),
        ApprovalStatus.APPROVED,
        reviewer_id="réviseur-42",
    )
    require_approved(approved, action_id)
    assert approved.reviewer_id == "réviseur-42"
