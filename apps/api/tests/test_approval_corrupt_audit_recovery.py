"""Corrupted persisted approval audit fields must fail closed after recovery."""

from uuid import uuid4

import pytest

from app.domain.approvals import (
    ApprovalDecision,
    ApprovalGateError,
    ApprovalStatus,
    decide,
    require_approved,
)


@pytest.mark.parametrize("invalid", [123, False, ["reviewer"], {"id": "reviewer"}])
def test_recovered_non_string_reviewer_never_authorizes(invalid: object) -> None:
    action_id = uuid4()
    decision = ApprovalDecision(
        action_id=action_id, status=ApprovalStatus.APPROVED, reviewer_id="reviewer"
    ).model_copy(update={"reviewer_id": invalid})
    with pytest.raises(ApprovalGateError, match="not been approved"):
        require_approved(decision, action_id)
    with pytest.raises(ApprovalGateError, match="Persisted approval decision is invalid"):
        decide(decision, ApprovalStatus.APPROVED, reviewer_id="reviewer")


@pytest.mark.parametrize("invalid", [123, False, ["reason"], {"reason": "ok"}])
def test_recovered_non_string_reason_never_authorizes(invalid: object) -> None:
    action_id = uuid4()
    decision = ApprovalDecision(
        action_id=action_id,
        status=ApprovalStatus.APPROVED,
        reviewer_id="reviewer",
        reason="checked",
    ).model_copy(update={"reason": invalid})
    with pytest.raises(ApprovalGateError, match="not been approved"):
        require_approved(decision, action_id)
    with pytest.raises(ApprovalGateError, match="Persisted approval decision is invalid"):
        decide(decision, ApprovalStatus.APPROVED, reviewer_id="reviewer")


def test_valid_recovered_approval_still_authorizes() -> None:
    action_id = uuid4()
    decision = ApprovalDecision(
        action_id=action_id,
        status=ApprovalStatus.APPROVED,
        reviewer_id="reviewer",
        reason="checked",
    )
    require_approved(decision, action_id)
    assert decide(
        decision, ApprovalStatus.APPROVED, reviewer_id="reviewer", reason="checked"
    ) == decision
