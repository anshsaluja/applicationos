"""Crash-recovery reconciliation must never mistake an intent for a receipt."""

import pytest

from app.api import requires_dispatch_reconciliation


@pytest.mark.parametrize(
    ("workflow_status", "outbox_status", "receipt_present", "receipt_valid", "expected"),
    [
        ("pending", None, False, False, False),
        ("awaiting_approval", None, False, False, False),
        ("ready", "pending", False, False, False),
        ("running", "pending", False, False, False),
        ("running", None, False, False, True),
        ("running", "claimed", False, False, True),
        ("running", "quarantined", False, False, True),
        ("running", "dispatched", False, False, True),
        ("running", "dispatched", True, True, False),
        ("succeeded", "dispatched", True, True, False),
        ("succeeded", "dispatched", False, False, True),
        ("succeeded", None, False, False, True),
        ("failed", "dispatched", True, True, True),
        ("ready", "pending", True, False, True),
        ("ready", "pending", True, True, True),
        ("running", "dispatched", True, False, True),
        ("succeeded", "dispatched", True, False, True),
    ],
)
def test_reconciliation_truth_table(
    workflow_status: str,
    outbox_status: str | None,
    receipt_present: bool,
    receipt_valid: bool,
    expected: bool,
) -> None:
    assert (
        requires_dispatch_reconciliation(
            workflow_status,
            outbox_status,
            receipt_valid,
            receipt_present=receipt_present,
        )
        is expected
    )


@pytest.mark.parametrize("workflow_status", ["pending", "ready", "running", "succeeded", "failed"])
@pytest.mark.parametrize("outbox_status", [None, "pending", "claimed", "dispatched", "quarantined"])
def test_present_invalid_receipt_always_requires_reconciliation(
    workflow_status: str, outbox_status: str | None
) -> None:
    assert requires_dispatch_reconciliation(
        workflow_status, outbox_status, False, receipt_present=True
    )
