"""Fail-closed regression checks for repeat synthetic dispatch acknowledgement."""
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.domain.workflows import WorkflowTransitionError
from app.persistence import (
    WorkflowOutboxRepository,
)


@pytest.mark.parametrize("checkpoint_status", [None, "failed", "pending", "ready"])
def test_repeated_synthetic_dispatch_rejects_missing_or_nonterminal_checkpoint(checkpoint_status):
    action_id = uuid4()
    session = MagicMock()
    outbox = SimpleNamespace(action_id=action_id, idempotency_key="key", status="dispatched")
    session.query.return_value.filter_by.return_value.with_for_update.return_value.one_or_none.side_effect = [
        outbox,
        None if checkpoint_status is None else SimpleNamespace(
            idempotency_key="key", status=checkpoint_status
        ),
    ]
    session.get.return_value = SimpleNamespace(idempotency_key="key", adapter="synthetic-noop")
    with pytest.raises(WorkflowTransitionError, match="Verified workflow"):
        WorkflowOutboxRepository(session).mark_dispatched(action_id, synthetic_receipt=True)


@pytest.mark.parametrize("checkpoint_status", ["running", "succeeded"])
def test_repeated_synthetic_dispatch_accepts_matching_active_or_completed_checkpoint(checkpoint_status):
    action_id = uuid4()
    session = MagicMock()
    outbox = SimpleNamespace(action_id=action_id, idempotency_key="key", status="dispatched")
    session.query.return_value.filter_by.return_value.with_for_update.return_value.one_or_none.side_effect = [
        outbox,
        SimpleNamespace(idempotency_key="key", status=checkpoint_status),
    ]
    session.get.return_value = SimpleNamespace(idempotency_key="key", adapter="synthetic-noop")
    assert WorkflowOutboxRepository(session).mark_dispatched(action_id, synthetic_receipt=True) is outbox


def test_repeated_synthetic_dispatch_rejects_mismatched_checkpoint_key():
    action_id = uuid4()
    session = MagicMock()
    outbox = SimpleNamespace(action_id=action_id, idempotency_key="key", status="dispatched")
    session.query.return_value.filter_by.return_value.with_for_update.return_value.one_or_none.side_effect = [
        outbox,
        SimpleNamespace(idempotency_key="other-key", status="succeeded"),
    ]
    session.get.return_value = SimpleNamespace(idempotency_key="key", adapter="synthetic-noop")
    with pytest.raises(WorkflowTransitionError, match="Verified workflow"):
        WorkflowOutboxRepository(session).mark_dispatched(action_id, synthetic_receipt=True)
