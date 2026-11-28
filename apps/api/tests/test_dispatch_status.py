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
        (None, None, True, False),
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
        SimpleNamespace(action_id=action_id, status=outbox_status, idempotency_key=key)
        if outbox_status is not None
        else None
    )
    receipt = (
        SimpleNamespace(
            action_id=action_id,
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
    assert result.synthetic_receipt_present is (receipt is not None)
    assert result.synthetic_receipt_valid is expected_receipt
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


@pytest.mark.parametrize("foreign_record", ["outbox", "receipt"])
def test_dispatch_status_rejects_foreign_action_evidence(monkeypatch, foreign_record):
    """A valid key cannot authenticate evidence for a different action."""
    action_id = uuid4()
    key = "same-key"
    state = SimpleNamespace(status=WorkflowStatus.SUCCEEDED, idempotency_key=key)
    outbox = SimpleNamespace(
        action_id=uuid4() if foreign_record == "outbox" else action_id,
        status="dispatched",
        idempotency_key=key,
    )
    receipt = SimpleNamespace(
        action_id=uuid4() if foreign_record == "receipt" else action_id,
        adapter="synthetic-noop",
        idempotency_key=key,
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
    assert result.synthetic_receipt_present is True
    assert result.synthetic_receipt_valid is False
    assert result.reconciliation_required is True
