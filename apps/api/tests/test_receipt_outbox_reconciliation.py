"""Fail-closed reconciliation when a receipt contradicts outbox state."""

import pytest

from app.api import requires_dispatch_reconciliation


@pytest.mark.parametrize("outbox_status", [None, "pending", "claimed", "quarantined"])
def test_receipt_before_dispatch_requires_reconciliation(outbox_status):
    assert requires_dispatch_reconciliation("running", outbox_status, True)


def test_dispatched_matching_receipt_is_consistent_while_running():
    assert not requires_dispatch_reconciliation("running", "dispatched", True)


def test_succeeded_without_dispatched_receipt_requires_reconciliation():
    assert requires_dispatch_reconciliation("succeeded", "pending", True)
