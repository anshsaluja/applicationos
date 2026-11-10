"""Read-only planning against durable database evidence.

Never trust caller-supplied workflow/approval snapshots to authorize a claim.
The graph is advisory; the transactional repository remains the sole execution gate.
"""
from __future__ import annotations

from uuid import UUID

from .domain.approvals import ApprovalStatus
from .persistence import (
    ApprovalRepository,
    SyntheticReceiptRow,
    WorkflowOutboxRow,
    WorkflowRepository,
)
from .planning_graph import build_planning_graph


def plan_persisted_workflow(session, action_id: UUID) -> dict[str, str] | None:
    """Return a fail-closed plan from one database transaction, without writes.

    An existing outbox intent permanently prevents this action identity from
    being recommended for another claim. Claimed, quarantined and dispatched
    intents require operator reconciliation; a valid completed receipt alone
    does not permit replay. This advisory snapshot can become stale immediately.
    """
    workflow = WorkflowRepository(session).get(action_id)
    if workflow is None:
        return None
    approval = ApprovalRepository(session).get(action_id)
    outbox = session.get(WorkflowOutboxRow, action_id)
    receipt = session.get(SyntheticReceiptRow, action_id)
    if outbox is not None or receipt is not None:
        if (
            workflow.status.value == "succeeded"
            and outbox is not None
            and outbox.status == "dispatched"
            and receipt is not None
            and outbox.action_id == action_id
            and receipt.action_id == action_id
            and approval is not None
            and approval.action_id == action_id
            and approval.status == ApprovalStatus.APPROVED
            and receipt.adapter == "synthetic-noop"
            and receipt.idempotency_key == workflow.idempotency_key
            and outbox.idempotency_key == workflow.idempotency_key
        ):
            return {
                "next_step": "complete",
                "explanation": "Matching durable synthetic receipt confirms completion",
            }
        return {
            "next_step": "reconcile",
            "explanation": "Existing dispatch evidence forbids planning another claim",
        }
    # A success checkpoint without matching dispatch evidence is inconsistent.
    if workflow.status.value == "succeeded":
        return {
            "next_step": "reconcile",
            "explanation": "Successful checkpoint lacks durable dispatch evidence",
        }
    result = build_planning_graph().invoke(
        {"workflow": workflow, "approval": approval, "next_step": "", "explanation": ""}
    )
    return {"next_step": result["next_step"], "explanation": result["explanation"]}
