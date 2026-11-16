"""Unit coverage for the final persisted approval boundary at synthetic completion."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.workflows import WorkflowTransitionError
from app.persistence import (
    SyntheticReceiptRow,
    WorkflowOutboxRepository,
    WorkflowOutboxRow,
    WorkflowRow,
)


class FakeQuery:
    def __init__(self, row):
        self.row = row

    def filter_by(self, **kwargs):
        return self

    def with_for_update(self):
        return self

    def one_or_none(self):
        return self.row


class FakeSession:
    def __init__(self, outbox, workflow, receipt):
        self.outbox = outbox
        self.workflow = workflow
        self.receipt = receipt
        self.flush_count = 0

    def query(self, model):
        if model is WorkflowOutboxRow:
            return FakeQuery(self.outbox)
        if model is WorkflowRow:
            return FakeQuery(self.workflow)
        raise AssertionError(f"Unexpected model: {model}")

    def get(self, model, action_id):
        assert model is SyntheticReceiptRow
        return self.receipt

    def flush(self):
        self.flush_count += 1


def make_session(status="running"):
    action_id = uuid4()
    key = "synthetic:approval-recheck"
    outbox = SimpleNamespace(action_id=action_id, idempotency_key=key, status="dispatched")
    workflow = SimpleNamespace(action_id=action_id, idempotency_key=key, status=status, last_error="previous")
    receipt = SimpleNamespace(action_id=action_id, idempotency_key=key, adapter="synthetic-noop")
    return action_id, FakeSession(outbox, workflow, receipt)


def test_synthetic_completion_rejects_invalid_persisted_approval(monkeypatch):
    action_id, session = make_session()
    repository = WorkflowOutboxRepository(session)
    monkeypatch.setattr(repository, "_has_valid_approval", lambda action: False)
    with pytest.raises(WorkflowTransitionError, match="Persisted approval required"):
        repository.complete_synthetic(action_id)
    assert session.workflow.status == "running"
    assert session.workflow.last_error == "previous"
    assert session.flush_count == 0


def test_synthetic_completion_accepts_valid_persisted_approval(monkeypatch):
    action_id, session = make_session()
    repository = WorkflowOutboxRepository(session)
    checked = []
    monkeypatch.setattr(repository, "_has_valid_approval", lambda action: checked.append(action) or True)
    result = repository.complete_synthetic(action_id)
    assert checked == [action_id]
    assert result.status == "succeeded"
    assert result.last_error is None
    assert session.flush_count == 1


def test_terminal_synthetic_replay_remains_read_only(monkeypatch):
    action_id, session = make_session(status="succeeded")
    repository = WorkflowOutboxRepository(session)
    monkeypatch.setattr(
        repository, "_has_valid_approval",
        lambda action: pytest.fail("Terminal replay must not reauthorize or mutate"),
    )
    assert repository.complete_synthetic(action_id).status == "succeeded"
    assert session.flush_count == 0
