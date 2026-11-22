"""Canonical reviewer identities must survive durable approval replay unchanged."""

from uuid import uuid4

import pytest

from app.domain.approvals import (
    ApprovalDecision,
    ApprovalGateError,
    ApprovalStatus,
    decide,
    require_approved,
)


@pytest.mark.parametrize("reviewer", ["re\u0301viseur-42", "a\u030aring-reviewer"])
def test_decomposed_reviewer_cannot_create_or_replay_approval(reviewer: str) -> None:
    action_id = uuid4()
    with pytest.raises(ApprovalGateError, match="valid reviewer identity"):
        decide(
            ApprovalDecision(action_id=action_id),
            ApprovalStatus.APPROVED,
            reviewer_id=reviewer,
        )

    persisted = ApprovalDecision(
        action_id=action_id,
        status=ApprovalStatus.APPROVED,
        reviewer_id=reviewer,
    )
    with pytest.raises(ApprovalGateError, match="not been approved"):
        require_approved(persisted, action_id)
    with pytest.raises(ApprovalGateError, match="Persisted approval decision is invalid"):
        decide(persisted, ApprovalStatus.APPROVED, reviewer_id=reviewer)


def test_precomposed_unicode_reviewer_remains_valid_and_idempotent() -> None:
    action_id = uuid4()
    reviewer = "réviseur-42"
    approved = decide(
        ApprovalDecision(action_id=action_id),
        ApprovalStatus.APPROVED,
        reviewer_id=reviewer,
        reason="Reviewed evidence",
    )
    require_approved(approved, action_id)
    assert decide(
        approved,
        ApprovalStatus.APPROVED,
        reviewer_id=reviewer,
        reason="Reviewed evidence",
    ) == approved
