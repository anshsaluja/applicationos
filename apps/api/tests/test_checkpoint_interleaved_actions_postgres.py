"""Verify PostgreSQL LangGraph checkpoints isolate concurrent action histories.

Requires a disposable TEST_DATABASE_URL; no external actions are dispatched.
"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

from app.domain.approvals import ApprovalDecision, ApprovalStatus
from app.domain.workflows import WorkflowState, WorkflowStatus
from app.durable_planning import checkpoint_config, postgres_planning_graph
from app.planning_graph import plan_with_fresh_evidence


def test_interleaved_actions_remain_isolated_across_planner_restarts():
    dsn = os.getenv("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL required for PostgreSQL integration")
    if not dsn.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.fail("TEST_DATABASE_URL must be a PostgreSQL DSN")

    approved_id, pending_id = uuid4(), uuid4()
    approved_config = checkpoint_config(approved_id)
    pending_config = checkpoint_config(pending_id)
    approved_workflow = WorkflowState(
        action_id=approved_id, idempotency_key=str(uuid4()), status=WorkflowStatus.READY
    )
    pending_workflow = WorkflowState(
        action_id=pending_id, idempotency_key=str(uuid4()), status=WorkflowStatus.READY
    )
    approval = ApprovalDecision(
        action_id=approved_id, status=ApprovalStatus.APPROVED, reviewer_id="test-reviewer"
    )

    with postgres_planning_graph(dsn, initialize=True) as graph:
        assert plan_with_fresh_evidence(
            graph, workflow=approved_workflow, approval=approval, config=approved_config
        )["next_step"] == "claim_outbox"
        assert plan_with_fresh_evidence(
            graph, workflow=pending_workflow, approval=None, config=pending_config
        )["next_step"] == "request_review"
        assert graph.get_state(pending_config).values["approval"] is None

    with postgres_planning_graph(dsn) as recovered:
        assert recovered.get_state(approved_config).values["approval"].action_id == approved_id
        assert recovered.get_state(pending_config).values["approval"] is None
        # Revoking A must not alter B's checkpoint, even when histories are interleaved.
        assert plan_with_fresh_evidence(
            recovered, workflow=approved_workflow, approval=None, config=approved_config
        )["next_step"] == "request_review"
        assert recovered.get_state(pending_config).values["approval"] is None

    with postgres_planning_graph(dsn) as recovered_again:
        assert recovered_again.get_state(approved_config).values["approval"] is None
        assert recovered_again.get_state(pending_config).values["approval"] is None
