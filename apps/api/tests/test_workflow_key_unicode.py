"""Validate workflow idempotency keys without a database or side effects."""

import pytest
from pydantic import ValidationError

from app.api import WorkflowCreateRequest

ACTION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


@pytest.mark.parametrize(
    "key",
    [
        "normal-key-123",
        "request:2026:11:10",
        "clé-2026",
    ],
)
def test_accepts_visible_idempotency_keys(key: str) -> None:
    payload = WorkflowCreateRequest(action_id=ACTION_ID, idempotency_key=key)
    assert payload.idempotency_key == key


@pytest.mark.parametrize(
    "key",
    [
        " leading",
        "trailing ",
        "middle space",
        "tab\tinside",
        "line\nfeed",
        "zero\u200bwidth",
        "right\u202eto-left",
        "isolate\u2066marker",
        "soft\u00adhyphen",
        "null\x00byte",
        "no\u00a0break",
    ],
)
def test_rejects_ambiguous_idempotency_keys(key: str) -> None:
    with pytest.raises(ValidationError, match="Idempotency key"):
        WorkflowCreateRequest(action_id=ACTION_ID, idempotency_key=key)
