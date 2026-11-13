"""Crash-recovery diagnostics must fail closed on unrecognized durable states."""

import pytest

from app.api import requires_dispatch_reconciliation


@pytest.mark.parametrize("workflow_status", ["unknown", "", "completed", "RUNNING"])
def test_unknown_workflow_states_require_reconciliation(workflow_status):
    assert requires_dispatch_reconciliation(workflow_status, None, False)


@pytest.mark.parametrize("outbox_status", ["unknown", "", "sent", "DISPATCHED"])
def test_unknown_outbox_states_require_reconciliation(outbox_status):
    assert requires_dispatch_reconciliation("ready", outbox_status, False)


def test_valid_pending_intent_does_not_require_reconciliation():
    assert not requires_dispatch_reconciliation("running", "pending", False)


def test_valid_dispatched_receipt_with_running_checkpoint_can_finish():
    assert not requires_dispatch_reconciliation("running", "dispatched", True)


def test_invalid_receipt_requires_reconciliation_even_for_pending_intent():
    assert requires_dispatch_reconciliation("running", "pending", False, receipt_present=True)
