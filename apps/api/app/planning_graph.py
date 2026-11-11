"""Side-effect-free LangGraph planning boundary.

The graph never dispatches actions or accepts an approval from document text.
Its output is advisory: the PostgreSQL workflow/outbox repositories remain
the source of truth for approval, idempotency and execution receipts.
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .domain.approvals import ApprovalDecision, ApprovalGateError, require_approved
from .domain.workflows import WorkflowState, WorkflowStatus


class PlanningState(TypedDict):
    workflow: WorkflowState
    approval: ApprovalDecision | None
    next_step: str
    explanation: str


def _route(state: PlanningState) -> dict[str, str]:
    workflow = state["workflow"]
    status = workflow.status

    if status == WorkflowStatus.SUCCEEDED:
        return {"next_step": "reconcile", "explanation": "Success requires independent durable receipt verification"}
    if status == WorkflowStatus.RUNNING:
        return {"next_step": "reconcile", "explanation": "Running action requires durable receipt reconciliation"}
    if status == WorkflowStatus.FAILED:
        return {"next_step": "reconcile", "explanation": "Failed action must be reconciled before retry"}
    if status == WorkflowStatus.PENDING:
        return {"next_step": "request_review", "explanation": "Action has not entered review"}

    try:
        require_approved(state["approval"], workflow.action_id)
    except ApprovalGateError:
        return {"next_step": "request_review", "explanation": "Verified human approval is required"}

    if status == WorkflowStatus.AWAITING_APPROVAL:
        return {"next_step": "persist_ready", "explanation": "Approval verified; persist transition before claim"}
    if status == WorkflowStatus.READY:
        return {"next_step": "claim_outbox", "explanation": "Recheck durable approval and idempotency atomically"}
    raise ValueError(f"Unsupported workflow status: {status}")


def build_planning_graph():
    """Compile a deterministic graph with no external effects.

    Checkpointing must be supplied by a durable runtime before using this
    graph for resumed execution; this graph itself does not claim durability.
    """
    graph = StateGraph(PlanningState)
    graph.add_node("plan", _route)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", END)
    return graph.compile()
