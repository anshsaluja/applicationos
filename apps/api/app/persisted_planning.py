"""Read-only planning against durable database evidence.

Never trust caller-supplied workflow/approval snapshots to authorize a claim.
The graph is advisory; the transactional repository remains the sole execution gate.
"""
from __future__ import annotations

from uuid import UUID

from .domain.approvals import ApprovalGateError, require_approved
from .persistence import (
    ApprovalRepository,
    SyntheticReceiptRow,
    WorkflowOutboxRow,
    WorkflowRepository,
)
from .durable_planning import checkpoint_config
from .planning_graph import build_planning_graph


def plan_persisted_workflow(session, action_id: UUID, *, graph=None) -> dict[str, str] | None:
    """Return a fail-closed plan from one database transaction.

    With an optional checkpointed graph, persist advisory planning state under
    the action's stable thread ID. Database evidence is always reloaded first;
    graph checkpoints never override approval, outbox or receipt checks.

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
    try:
        require_approved(approval, action_id)
        approval_verified = True
    except ApprovalGateError:
        approval_verified = False
    if outbox is not None or receipt is not None:
        if (
            workflow.status.value == "succeeded"
            and outbox is not None
            and outbox.status == "dispatched"
            and receipt is not None
            and outbox.action_id == action_id
            and receipt.action_id == action_id
            and approval_verified
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
    planner = graph if graph is not None else build_planning_graph()
    state = {"workflow": workflow, "approval": approval, "next_step": "", "explanation": ""}
    if graph is not None:
        result = planner.invoke(state, config=checkpoint_config(action_id))
    else:
        result = planner.invoke(state)
    return {"next_step": result["next_step"], "explanation": result["explanation"]}
