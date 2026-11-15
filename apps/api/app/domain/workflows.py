"""Pure, fail-closed workflow transition policy.

This module records *intent* only. It never invokes tools, sends messages,
or treats a supplied reviewer identity as authenticated. Durable storage and
an authenticated execution boundary must be added before external actions.
"""
from __future__ import annotations

from enum import StrEnum
import unicodedata
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from .approvals import ApprovalDecision, ApprovalGateError, require_approved


class WorkflowStatus(StrEnum):
    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class WorkflowTransitionError(ValueError):
    pass


def validate_workflow_idempotency_key(value: str) -> str:
    """Shared HTTP/domain validation; never normalize or alias caller keys."""
    if value != value.strip() or any(
        ch.isspace() or unicodedata.category(ch) in {"Cc", "Cf"} for ch in value
    ):
        raise ValueError("Idempotency key must not contain whitespace or invisible control/format characters")
    return value


class WorkflowState(BaseModel):
    action_id: UUID
    status: WorkflowStatus = WorkflowStatus.PENDING
    attempt: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1, le=10)
    idempotency_key: str = Field(min_length=1, max_length=200)
    last_error: str | None = None

    @field_validator("idempotency_key")
    @classmethod
    def reject_blank_idempotency_key(cls, value: str) -> str:
        """Match HTTP key rules even for internal and recovered workflow states."""
        return validate_workflow_idempotency_key(value)


def transition(
    state: WorkflowState,
    target: WorkflowStatus,
    *,
    approval: ApprovalDecision | None = None,
) -> WorkflowState:
    """Return a new state; forbid invalid or unsafe transitions.

    The caller must persist the state atomically before dispatching any work.
    A READY state is not authorization to perform a side effect: the execution
    boundary must independently recheck approval and idempotency.
    """
    # Reject corrupted or stale persisted checkpoints before even an idempotent
    # replay can make them appear authorized. A READY checkpoint at the retry
    # limit cannot legitimately be dispatched again.
    if state.attempt > state.max_attempts:
        raise WorkflowTransitionError("Invalid execution attempt")
    # A persisted RUNNING checkpoint must represent a claimed execution.
    # Reject zero-attempt corruption on every transition, not only replay or
    # dispatch; otherwise a fabricated checkpoint could become SUCCEEDED.
    if state.status == WorkflowStatus.RUNNING and state.attempt == 0:
        raise WorkflowTransitionError("Invalid execution attempt")
    if state.status == WorkflowStatus.READY and state.attempt >= state.max_attempts:
        raise WorkflowTransitionError("Retry budget exhausted")

    if target == state.status:
        # Idempotent reads of an executable state must not bypass the approval
        # boundary if the durable decision has been revoked or is unavailable.
        if target == WorkflowStatus.RUNNING and not 1 <= state.attempt <= state.max_attempts:
            raise WorkflowTransitionError("Invalid execution attempt")
        if target in {WorkflowStatus.READY, WorkflowStatus.RUNNING}:
            try:
                require_approved(approval, state.action_id)
            except ApprovalGateError as exc:
                raise WorkflowTransitionError("Verified approval is required") from exc
        return state.model_copy(deep=True)

    allowed = {
        WorkflowStatus.PENDING: {WorkflowStatus.AWAITING_APPROVAL},
        WorkflowStatus.AWAITING_APPROVAL: {WorkflowStatus.READY, WorkflowStatus.FAILED},
        WorkflowStatus.READY: {WorkflowStatus.RUNNING},
        WorkflowStatus.RUNNING: {WorkflowStatus.SUCCEEDED, WorkflowStatus.FAILED},
        WorkflowStatus.FAILED: {WorkflowStatus.READY},
        WorkflowStatus.SUCCEEDED: set(),
    }
    if target not in allowed[state.status]:
        raise WorkflowTransitionError(f"Invalid transition: {state.status} -> {target}")

    if target in {WorkflowStatus.READY, WorkflowStatus.RUNNING}:
        try:
            require_approved(approval, state.action_id)
        except ApprovalGateError as exc:
            raise WorkflowTransitionError("Verified approval is required") from exc

    if target == WorkflowStatus.READY and state.attempt >= state.max_attempts:
        raise WorkflowTransitionError("Retry budget exhausted")

    if target == WorkflowStatus.RUNNING:
        if state.attempt >= state.max_attempts:
            raise WorkflowTransitionError("Retry budget exhausted")
        return state.model_copy(update={"status": target, "attempt": state.attempt + 1, "last_error": None})

    return state.model_copy(update={"status": target})


def require_dispatch_authorization(
    state: WorkflowState, *, approval: ApprovalDecision | None = None
) -> None:
    """Fail closed immediately before dispatching a consequential action.

    Callers must load the current durable approval and workflow state inside
    the same transaction used to claim the idempotency key. This pure guard
    alone does not provide atomicity or prevent duplicate external effects.
    """
    if state.status != WorkflowStatus.RUNNING:
        raise WorkflowTransitionError("Workflow must be running before dispatch")
    if not 1 <= state.attempt <= state.max_attempts:
        raise WorkflowTransitionError("Invalid execution attempt")
    try:
        require_approved(approval, state.action_id)
    except ApprovalGateError as exc:
        raise WorkflowTransitionError("Verified approval is required for dispatch") from exc
