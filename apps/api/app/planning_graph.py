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

    # Recovered checkpoints are advisory, but must never suggest dispatch for
    # exhausted or internally inconsistent execution counters. The durable
    # repository remains the final transactional authorization boundary.
    if (
        not 1 <= workflow.max_attempts <= 10
        or not 0 <= workflow.attempt <= workflow.max_attempts
    ):
        return {"next_step": "reconcile", "explanation": "Invalid execution attempt requires reconciliation"}
    if status in {WorkflowStatus.RUNNING, WorkflowStatus.SUCCEEDED} and workflow.attempt == 0:
        return {"next_step": "reconcile", "explanation": "Missing execution claim requires reconciliation"}
    if status in {WorkflowStatus.READY, WorkflowStatus.AWAITING_APPROVAL} and workflow.attempt >= workflow.max_attempts:
        return {"next_step": "reconcile", "explanation": "Retry budget exhausted; do not claim execution"}

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


def build_planning_graph(*, checkpointer=None):
    """Compile a side-effect-free planner with an optional runtime checkpointer.

    A production caller must provide a durable checkpointer and a stable
    thread_id to resume a workflow. Without one, invocations are ephemeral.
    Even with checkpoints, graph output never authorizes dispatch: the
    transactional repository must revalidate approval and outbox evidence.
    """
    graph = StateGraph(PlanningState)
    graph.add_node("plan", _route)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", END)
    return graph.compile(checkpointer=checkpointer)


def plan_with_fresh_evidence(graph, *, workflow: WorkflowState, approval: ApprovalDecision | None, config=None):
    """Replan from caller-supplied durable state, never inherited checkpoint approval.

    LangGraph merges partial inputs with saved state. Always overwrite approval,
    including with None after revocation or when evidence is unavailable.
    A saved next_step is advisory and is reset before each evaluation.
    """
    if not isinstance(workflow, WorkflowState):
        raise TypeError("workflow must be a WorkflowState")
    if approval is not None and not isinstance(approval, ApprovalDecision):
        raise TypeError("approval must be an ApprovalDecision or None")
    # Reject foreign approval evidence before LangGraph can persist it in this thread.
    # The route gate also checks identity, but checkpoint contents must stay isolated.
    if approval is not None and approval.action_id != workflow.action_id:
        raise ValueError("Approval action_id must match workflow action_id")
    if config is not None:
        if not isinstance(config, dict) or not isinstance(config.get("configurable"), dict):
            raise ValueError("Checkpoint config must contain a configurable thread_id")
        thread_id = config["configurable"].get("thread_id")
        if thread_id != str(workflow.action_id):
            raise ValueError("Checkpoint thread_id must match workflow action_id")
        # A caller-provided checkpoint_id selects an older snapshot. Fresh planning
        # must use the latest state rather than fork from a stale approval.
        # Namespaces other than the default are not part of this action boundary.
        configurable = config["configurable"]
        # Do not let caller-supplied checkpoint routing fields alter isolation.
        # Only the stable action thread and explicit default namespace are valid.
        unexpected = set(configurable) - {"thread_id", "checkpoint_ns", "checkpoint_id"}
        if unexpected:
            raise ValueError("Fresh planning rejects unexpected checkpoint configuration keys")
        if "checkpoint_id" in configurable:
            raise ValueError("Fresh planning must not select a historical checkpoint_id")
        if configurable.get("checkpoint_ns", "") != "":
            raise ValueError("Fresh planning requires the default checkpoint namespace")
    return graph.invoke(
        {"workflow": workflow, "approval": approval, "next_step": "", "explanation": ""},
        config=config,
    )
