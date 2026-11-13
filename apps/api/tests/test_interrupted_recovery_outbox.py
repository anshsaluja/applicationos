"""Regression tests for fail-closed interrupted-worker reconciliation."""
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.domain.workflows import WorkflowTransitionError
from app.persistence import WorkflowRepository


def make_repository(outbox_status: str | None):
    action_id = uuid4()
    workflow = SimpleNamespace(
        action_id=action_id,
        idempotency_key="recovery-test",
        status="running",
        attempt=1,
        max_attempts=3,
        last_error=None,
    )
    outbox = None if outbox_status is None else SimpleNamespace(status=outbox_status)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.with_for_update.return_value.one_or_none.side_effect = [
        workflow,
        outbox,
    ]
    return WorkflowRepository(session), workflow, outbox, session, action_id


@pytest.mark.parametrize("status", ["pending", "claimed"])
def test_recovery_quarantines_unfinished_intent(status):
    repository, workflow, outbox, session, action_id = make_repository(status)
    result = repository.recover_interrupted(action_id, reason="Worker stopped")
    assert result.status.value == "failed"
    assert workflow.status == "failed"
    assert workflow.last_error == "Worker stopped"
    assert outbox.status == "quarantined"
    session.flush.assert_called_once()


def test_recovery_refuses_confirmed_dispatch():
    repository, workflow, outbox, session, action_id = make_repository("dispatched")
    with pytest.raises(WorkflowTransitionError, match="receipt reconciliation"):
        repository.recover_interrupted(action_id)
    assert workflow.status == "running"
    assert outbox.status == "dispatched"
    session.flush.assert_not_called()


def test_recovery_without_outbox_fails_checkpoint_only():
    repository, _workflow, _, session, action_id = make_repository(None)
    result = repository.recover_interrupted(action_id)
    assert result.status.value == "failed"
    session.flush.assert_called_once()


@pytest.mark.parametrize("status", ["unknown", "retrying", ""])
def test_recovery_rejects_unknown_persisted_outbox_status(status):
    repository, workflow, outbox, session, action_id = make_repository(status)
    with pytest.raises(WorkflowTransitionError, match="Unknown outbox state"):
        repository.recover_interrupted(action_id)
    assert workflow.status == "running"
    assert outbox.status == status
    session.flush.assert_not_called()


def test_recovery_accepts_already_quarantined_outbox_without_replay():
    repository, workflow, outbox, session, action_id = make_repository("quarantined")
    result = repository.recover_interrupted(action_id)
    assert result.status.value == "failed"
    assert outbox.status == "quarantined"
    session.flush.assert_called_once()
