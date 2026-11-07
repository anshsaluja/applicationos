"""Local-only synthetic outbox consumer.

This worker deliberately performs NO external I/O. A successful run proves only
that a claimed, approved intent can be acknowledged by the synthetic adapter.
It is not suitable for real-world actions or public deployment.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .persistence import WorkflowOutboxRepository


@dataclass(frozen=True)
class SyntheticDispatchReceipt:
    action_id: UUID
    idempotency_key: str
    adapter: str = "synthetic-noop"


def dispatch_one_synthetic(session_factory, *, action_id: UUID | None = None):
    """Claim, commit, then acknowledge one synthetic no-op dispatch.

    Claim and confirmation use separate transactions to model the crash
    boundary. If anything interrupts after claiming, the intent remains
    claimed and MUST be reconciled; it is never automatically replayed.
    """
    with session_factory.begin() as session:
        claimed = WorkflowOutboxRepository(session).claim_next_pending(action_id=action_id)
        if claimed is None:
            return None
        receipt = SyntheticDispatchReceipt(
            action_id=claimed.action_id,
            idempotency_key=claimed.idempotency_key,
        )

    # No network calls, filesystem writes, or other external effects here.
    # Future effect adapters require durable receipts and external idempotency.
    with session_factory.begin() as session:
        WorkflowOutboxRepository(session).mark_dispatched(receipt.action_id)
    return receipt
