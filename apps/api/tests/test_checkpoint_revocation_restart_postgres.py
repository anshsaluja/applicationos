"""PostgreSQL recovery must not resurrect revoked approval evidence.

Uses the isolated TEST_DATABASE_URL supplied by CI; never a production database.
"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

from app.domain.approvals import ApprovalDecision, ApprovalStatus
from app.domain.workflows import WorkflowState, WorkflowStatus
from app.durable_planning import checkpoint_config, postgres_planning_graph
from app.planning_graph import plan_with_fresh_evidence


def test_reopened_checkpoint_rechecks_revocation_and_restored_approval():
    dsn = os.getenv("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL required for PostgreSQL integration")
    if not dsn.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.fail("TEST_DATABASE_URL must be a PostgreSQL DSN")
    dsn = dsn.replace("postgresql+psycopg://", "postgresql://", 1)

    action_id = uuid4()
    config = checkpoint_config(action_id)
    workflow = WorkflowState(
        action_id=action_id, idempotency_key=str(uuid4()), status=WorkflowStatus.READY
    )
    approved = ApprovalDecision(
        action_id=action_id, status=ApprovalStatus.APPROVED, reviewer_id="recovery-reviewer"
    )

    with postgres_planning_graph(dsn, initialize=True) as initial:
        assert plan_with_fresh_evidence(
            initial, workflow=workflow, approval=approved, config=config
        )["next_step"] == "claim_outbox"

    # A restarted process has no approval evidence: the checkpoint's prior
    # approval must not silently authorize another claim recommendation.
    with postgres_planning_graph(dsn) as recovered:
        assert recovered.get_state(config).values["approval"].status == ApprovalStatus.APPROVED
        revoked = plan_with_fresh_evidence(
            recovered, workflow=workflow, approval=None, config=config
        )
        assert revoked["next_step"] == "request_review"
        assert recovered.get_state(config).values["approval"] is None

    # A second restart must retain the denial until fresh durable approval is supplied.
    with postgres_planning_graph(dsn) as recovered_again:
        assert recovered_again.get_state(config).values["next_step"] == "request_review"
        assert recovered_again.get_state(config).values["approval"] is None
        restored = plan_with_fresh_evidence(
            recovered_again, workflow=workflow, approval=approved, config=config
        )
        assert restored["next_step"] == "claim_outbox"
        assert recovered_again.get_state(config).values["approval"].action_id == action_id
