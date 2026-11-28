"""Unknown checkpoint workflow statuses fail closed instead of breaking recovery."""
from uuid import uuid4

import pytest

from app.domain.workflows import WorkflowState
from app.planning_graph import _route


@pytest.mark.parametrize("corrupt_status", ["EXECUTING", "ready", "", None, 42, {}])
def test_unknown_recovered_status_requires_reconciliation(corrupt_status: object) -> None:
    workflow = WorkflowState(action_id=uuid4(), idempotency_key=str(uuid4())).model_copy(
        update={"status": corrupt_status}
    )
    result = _route({"workflow": workflow, "approval": None, "next_step": "", "explanation": ""})
    assert result["next_step"] == "reconcile"
    assert "Unknown workflow status" in result["explanation"]
