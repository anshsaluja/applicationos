"""Reject private-use Unicode in reviewer and approval audit fields.

Private-use code points have no stable public glyph, so accepting them can
make distinct identities or reasons appear identical in audit interfaces.
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


@pytest.mark.parametrize("character", ["\ue000", "\uf8ff", "\U000f0000"])
def test_private_use_reviewer_cannot_decide_or_authorize(character: str) -> None:
    action_id = uuid4()
    reviewer = f"reviewer{character}42"
    with pytest.raises(ApprovalGateError, match="valid reviewer"):
        decide(
            ApprovalDecision(action_id=action_id),
            ApprovalStatus.APPROVED,
            reviewer_id=reviewer,
        )
    forged = ApprovalDecision(
        action_id=action_id,
        status=ApprovalStatus.APPROVED,
        reviewer_id=reviewer,
    )
    with pytest.raises(ApprovalGateError, match="not been approved"):
        require_approved(forged, action_id)


@pytest.mark.parametrize("character", ["\ue000", "\uf8ff", "\U000f0000"])
def test_private_use_audit_reason_is_rejected(character: str) -> None:
    action_id = uuid4()
    reason = f"Reviewed{character}evidence"
    with pytest.raises(ApprovalGateError, match="Invalid approval reason"):
        decide(
            ApprovalDecision(action_id=action_id),
            ApprovalStatus.REJECTED,
            reviewer_id="reviewer-42",
            reason=reason,
        )
    corrupted = ApprovalDecision(
        action_id=action_id,
        status=ApprovalStatus.APPROVED,
        reviewer_id="reviewer-42",
        reason=reason,
    )
    with pytest.raises(ApprovalGateError, match="not been approved"):
        require_approved(corrupted, action_id)
