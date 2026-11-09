"""Dispatch reconciliation diagnostics must never imply an unverified effect succeeded."""

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app import api
from app.domain.workflows import WorkflowStatus
from app.persistence import SyntheticReceiptRow, WorkflowOutboxRow


@pytest.mark.parametrize(
    ("outbox_status", "receipt_key", "expected_reconciliation", "expected_receipt"),
    [
        (None, None, False, False),
        ("claimed", None, True, False),
        ("quarantined", None, True, False),
        ("dispatched", None, True, False),
        ("dispatched", "matching", False, True),
        ("dispatched", "wrong", True, False),
    ],
)
def test_dispatch_status_reconciliation(
    monkeypatch, outbox_status, receipt_key, expected_reconciliation, expected_receipt
):
    action_id = uuid4()
    key = "workflow-idempotency"
    state = SimpleNamespace(status=WorkflowStatus.RUNNING, idempotency_key=key)
    outbox = (
        SimpleNamespace(status=outbox_status, idempotency_key=key)
        if outbox_status is not None
        else None
    )
    receipt = (
        SimpleNamespace(
            adapter="synthetic-noop",
            idempotency_key=key if receipt_key == "matching" else "different",
        )
        if receipt_key is not None
        else None
    )

    class FakeSession:
        def get(self, model, requested_id):
            assert requested_id == action_id
            if model is WorkflowOutboxRow:
                return outbox
            if model is SyntheticReceiptRow:
                return receipt
            raise AssertionError("Unexpected model")

    @contextmanager
    def fake_scope(_factory):
        yield FakeSession()

    monkeypatch.setattr(api, "session_scope", fake_scope)
    monkeypatch.setattr(api, "get_session_factory", lambda: None)
    monkeypatch.setattr("app.persistence.WorkflowRepository.get", lambda self, _: state)

    result = api.get_workflow_dispatch_status(action_id)
    assert result.outbox_status == outbox_status
    assert result.synthetic_receipt_present is expected_receipt
    assert result.reconciliation_required is expected_reconciliation


def test_dispatch_status_missing_workflow_is_404(monkeypatch):
    @contextmanager
    def fake_scope(_factory):
        yield object()

    monkeypatch.setattr(api, "session_scope", fake_scope)
    monkeypatch.setattr(api, "get_session_factory", lambda: None)
    monkeypatch.setattr("app.persistence.WorkflowRepository.get", lambda self, _: None)

    with pytest.raises(HTTPException) as exc:
        api.get_workflow_dispatch_status(uuid4())
    assert exc.value.status_code == 404
