"""Fail-closed approval identity and persisted-record boundary tests.

Pure domain regressions; concurrency and durable database behavior are covered separately.
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


@pytest.mark.parametrize(
    "reviewer_id",
    [
        "",
        " reviewer",
        "reviewer ",
        "reviewer\tadmin",
        "reviewer\nadmin",
        "reviewer\u200badmin",
        "reviewer\u202eadmin",
        "x" * 129,
    ],
)
def test_invalid_reviewer_cannot_create_approval(reviewer_id: str) -> None:
    with pytest.raises(ApprovalGateError, match="valid reviewer identity"):
        decide(ApprovalDecision(action_id=uuid4()), ApprovalStatus.APPROVED, reviewer_id=reviewer_id)


@pytest.mark.parametrize(
    "reviewer_id",
    [" ", "reviewer\nadmin", "reviewer\u200badmin", "x" * 129],
)
def test_persisted_approval_with_invalid_reviewer_cannot_execute(reviewer_id: str) -> None:
    action_id = uuid4()
    persisted = ApprovalDecision(
        action_id=action_id, status=ApprovalStatus.APPROVED, reviewer_id=reviewer_id
    )
    with pytest.raises(ApprovalGateError, match="not been approved"):
        require_approved(persisted, action_id)


def test_approval_for_different_action_cannot_execute() -> None:
    decision = decide(
        ApprovalDecision(action_id=uuid4()), ApprovalStatus.APPROVED, reviewer_id="reviewer"
    )
    with pytest.raises(ApprovalGateError, match="No matching approval decision"):
        require_approved(decision, uuid4())


@pytest.mark.parametrize("reason", ["unsafe\u202econtrol", "unsafe\x00control"])
def test_invalid_persisted_reason_blocks_execution_and_replay(reason: str) -> None:
    action_id = uuid4()
    corrupted = ApprovalDecision(
        action_id=action_id,
        status=ApprovalStatus.APPROVED,
        reviewer_id="reviewer",
        reason=reason,
    )
    with pytest.raises(ApprovalGateError, match="not been approved"):
        require_approved(corrupted, action_id)
    with pytest.raises(ApprovalGateError, match="Persisted approval decision is invalid"):
        decide(corrupted, ApprovalStatus.APPROVED, reviewer_id="reviewer", reason=reason)
