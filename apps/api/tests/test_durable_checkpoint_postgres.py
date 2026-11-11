"""Real PostgreSQL checkpoint persistence across independent planner lifetimes.

Run only with a disposable TEST_DATABASE_URL; CI supplies its isolated pgvector service.
No production database should be used for this integration test.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from app.domain.approvals import ApprovalDecision, ApprovalStatus
from app.domain.workflows import WorkflowState, WorkflowStatus
from app.durable_planning import checkpoint_config, postgres_planning_graph


def test_postgres_checkpoint_survives_reopened_connection_and_isolates_threads():
    dsn = os.getenv("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL required for PostgreSQL integration")
    if not dsn.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.fail("TEST_DATABASE_URL must be a PostgreSQL DSN")
    # PostgresSaver uses psycopg directly, not SQLAlchemy's dialect-prefixed URL.
    dsn = dsn.replace("postgresql+psycopg://", "postgresql://", 1)
    action_id, other_id = uuid4(), uuid4()
    config = checkpoint_config(action_id)
    workflow = WorkflowState(
        action_id=action_id, idempotency_key=str(uuid4()), status=WorkflowStatus.READY
    )
    approval = ApprovalDecision(
        action_id=action_id, status=ApprovalStatus.APPROVED, reviewer_id="integration-reviewer"
    )

    with postgres_planning_graph(dsn, initialize=True) as graph:
        result = graph.invoke(
            {"workflow": workflow, "approval": approval, "next_step": "", "explanation": ""},
            config=config,
        )
        assert result["next_step"] == "claim_outbox"
        assert graph.get_state(config).next == ()

    # A new connection and newly compiled graph must recover the prior state.
    with postgres_planning_graph(dsn) as recovered:
        snapshot = recovered.get_state(config)
        assert snapshot.values["workflow"].action_id == action_id
        assert snapshot.values["next_step"] == "claim_outbox"
        assert snapshot.next == ()
        assert not recovered.get_state(checkpoint_config(other_id)).values
        # A persisted recommendation is never a dispatch authorization.
        assert "receipt" not in snapshot.values
