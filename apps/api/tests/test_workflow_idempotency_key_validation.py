"""Keep the domain idempotency-key boundary aligned with the HTTP contract."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.workflows import WorkflowState


@pytest.mark.parametrize(
    "key",
    [
        "", " ", "\t", "\n", " \t\n ", " leading", "trailing ",
        "middle space", "tab\tinside", "line\nfeed", "zero\u200bwidth",
        "right\u202eto-left", "isolate\u2066marker", "soft\u00adhyphen",
        "null\x00byte", "no\u00a0break",
    ],
)
def test_ambiguous_idempotency_keys_are_rejected(key: str) -> None:
    with pytest.raises(ValidationError, match="Idempotency key"):
        WorkflowState(action_id=uuid4(), idempotency_key=key)


@pytest.mark.parametrize("key", ["request-42", "request:2026:11:15", "clé-2026"])
def test_visible_idempotency_key_is_preserved(key: str) -> None:
    state = WorkflowState(action_id=uuid4(), idempotency_key=key)
    assert state.idempotency_key == key


def test_overlong_idempotency_key_is_rejected() -> None:
    with pytest.raises(ValidationError):
        WorkflowState(action_id=uuid4(), idempotency_key="x" * 201)
