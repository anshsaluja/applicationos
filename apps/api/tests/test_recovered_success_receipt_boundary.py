"""PostgreSQL recovery must not treat a checkpointed success as an execution receipt.

Uses only the disposable TEST_DATABASE_URL supplied by CI.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from app.domain.approvals import ApprovalDecision, ApprovalStatus
from app.domain.workflows import WorkflowState, WorkflowStatus
from app.durable_planning import checkpoint_config, postgres_planning_graph


def test_recovered_success_requires_independent_receipt_reconciliation():
    dsn = os.getenv("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL required for PostgreSQL integration")
    if not dsn.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.fail("TEST_DATABASE_URL must point to disposable PostgreSQL")

    action_id = uuid4()
    key = str(uuid4())
    config = checkpoint_config(action_id)
    approval = ApprovalDecision(
        action_id=action_id,
        status=ApprovalStatus.APPROVED,
        reviewer_id="integration-reviewer",
    )

    def workflow(status):
        return WorkflowState(
            action_id=action_id, idempotency_key=key, status=status
        )

    with postgres_planning_graph(dsn, initialize=True) as graph:
        result = graph.invoke(
            {
                "workflow": workflow(WorkflowStatus.READY),
                "approval": approval,
                "next_step": "",
                "explanation": "",
            },
            config=config,
        )
        assert result["next_step"] == "claim_outbox"

    # A different process reports success while the planner is offline.
    # Checkpoint output cannot replace an independently persisted receipt.
    with postgres_planning_graph(dsn) as recovered:
        assert recovered.get_state(config).values["next_step"] == "claim_outbox"
        result = recovered.invoke(
            {
                "workflow": workflow(WorkflowStatus.SUCCEEDED),
                "approval": approval,
                "next_step": "",
                "explanation": "",
            },
            config=config,
        )
        assert result["next_step"] == "reconcile"
        assert "receipt" not in result

    with postgres_planning_graph(dsn) as reopened:
        snapshot = reopened.get_state(config)
        assert snapshot.values["workflow"].status == WorkflowStatus.SUCCEEDED
        assert snapshot.values["next_step"] == "reconcile"
        assert "receipt" not in snapshot.values
