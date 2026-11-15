"""Ensure HTTP and durable workflow keys use exactly the same safety policy."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api import WorkflowCreateRequest
from app.domain.workflows import WorkflowState


@pytest.mark.parametrize("key", [
    "request-123", "clé-2026", "request:2026:11:15",
    " leading", "trailing ", "embedded space", "line\nfeed",
    "zero\u200bwidth", "right\u202eto-left", "null\x00byte",
    "soft\u00adhyphen", "no\u00a0break",
])
def test_http_and_domain_share_key_policy(key: str) -> None:
    action_id = uuid4()
    outcomes = []
    for model in (WorkflowCreateRequest, WorkflowState):
        try:
            instance = model(action_id=action_id, idempotency_key=key)
        except ValidationError:
            outcomes.append(False)
        else:
            assert instance.idempotency_key == key
            outcomes.append(True)
    assert outcomes[0] == outcomes[1], f"HTTP/domain key policy drift for {key!r}"
