"""Approval audit reasons must remain canonical across persistence and replay."""

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
def test_decomposed_reason_rejected_at_decision_boundary(status: ApprovalStatus) -> None:
    with pytest.raises(ApprovalGateError, match="Invalid approval reason"):
        decide(
            ApprovalDecision(action_id=uuid4()),
            status,
            reviewer_id="reviewer-1",
            reason="re\u0301viewed",
        )


@pytest.mark.parametrize("status", [ApprovalStatus.APPROVED, ApprovalStatus.REJECTED])
def test_corrupt_persisted_reason_cannot_authorize_or_replay(status: ApprovalStatus) -> None:
    action_id = uuid4()
    persisted = ApprovalDecision(
        action_id=action_id,
        status=status,
        reviewer_id="reviewer-1",
        reason="re\u0301viewed",
    )
    with pytest.raises(ApprovalGateError, match="not been approved"):
        require_approved(persisted, action_id)
    with pytest.raises(ApprovalGateError, match="Persisted approval decision is invalid"):
        decide(
            persisted,
            status,
            reviewer_id="reviewer-1",
            reason="réviewed",
        )


def test_precomposed_reason_round_trips_and_replays() -> None:
    action_id = uuid4()
    approved = decide(
        ApprovalDecision(action_id=action_id),
        ApprovalStatus.APPROVED,
        reviewer_id="reviewer-1",
        reason="réviewed",
    )
    restored = ApprovalDecision.model_validate_json(approved.model_dump_json())
    require_approved(restored, action_id)
    assert decide(
        restored,
        ApprovalStatus.APPROVED,
        reviewer_id="reviewer-1",
        reason="réviewed",
    ) == approved
