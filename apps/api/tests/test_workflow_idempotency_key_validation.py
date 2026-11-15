"""Reject unusable workflow idempotency keys at the model boundary."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.workflows import WorkflowState


@pytest.mark.parametrize("key", ["", " ", "\t", "\n", " \t\n "])
def test_blank_idempotency_keys_are_rejected(key):
    with pytest.raises(ValidationError):
        WorkflowState(action_id=uuid4(), idempotency_key=key)


def test_nonblank_idempotency_key_is_preserved():
    key = " request-42 "
    state = WorkflowState(action_id=uuid4(), idempotency_key=key)
    assert state.idempotency_key == key


def test_overlong_idempotency_key_is_rejected():
    with pytest.raises(ValidationError):
        WorkflowState(action_id=uuid4(), idempotency_key="x" * 201)
