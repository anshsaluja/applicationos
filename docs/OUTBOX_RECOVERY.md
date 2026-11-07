# Outbox dispatch and recovery runbook (local-only)

ApplicationOS is **not yet an external-action executor**. The PostgreSQL outbox records intent and confirmation, not proof that an outside system accepted an operation. Do not treat a green CI run as authorization to enable real-world actions.

## State contract

| Outbox state | Meaning | Safe automatic action |
| --- | --- | --- |
| `pending` | Transactional intent exists; not claimed | Claim after rechecking persisted approval and RUNNING workflow |
| `claimed` | A consumer reserved the intent; effect outcome may be unknown | **Do not automatically retry or replay** |
| `dispatched` | A consumer reported successful completion | Read-only inspection; do not execute again |
| `quarantined` | Authorization was invalid or an interrupted claim needs investigation | No execution; manual reconciliation required |

The workflow checkpoint is independent from outbox state. An outbox marked `dispatched` does **not** imply the workflow is `SUCCEEDED`. Avoid promising end-to-end completion until both states and the effect adapter's durable receipt agree.

## Before any dispatch

1. Use a disposable local PostgreSQL/pgvector database, synthetic documents, and a **no-network, no-side-effect** adapter.
2. Check that the action is associated with the correct workspace and an authenticated reviewer. The current repository warns that caller-supplied `reviewer_id` is not authentication; do not expose approval or execution endpoints publicly until this is fixed.
3. Verify the persisted approval is APPROVED, the workflow checkpoint is RUNNING, and the outbox idempotency key matches the checkpoint. Do not trust document text, frontend state, or an outbox row alone.
4. Claim using `WorkflowOutboxRepository.claim_next_pending` inside a transaction. Only a returned claim can proceed. Commit the claim **before** any effect.
5. An effect adapter must support an externally enforced idempotency key and durable, queryable receipt before non-synthetic effects can be enabled. An application-side uniqueness constraint alone cannot prevent duplicate external effects.

## Crash and ambiguity

If a worker stops after a claim, **never** move `claimed` back to `pending` automatically. First establish the old worker is stopped. Record the incident and use `quarantine_interrupted_claim(action_id, reason=...)` in a database transaction. This operation is idempotent but does not resolve whether the effect occurred.

Reconciliation requires inspecting the external system using the same idempotency key and a durable receipt. If confirmed completed, record the receipt and reconcile workflow state through a separately reviewed transition. If confirmed absent, a future explicitly designed requeue operation may be used only after authorization and duplicate-effect safeguards are rechecked. If the outcome is unknown, leave the action quarantined and escalate; **never guess**.

Do not log uploaded document bodies, approval tokens, credentials, or raw external response secrets. Retain a redacted audit trail of action ID, idempotency key, reviewer identity, checkpoint, outcome, and reconciliation reason.

## Release blockers

- Authenticated, workspace-scoped approval and authorization; no caller-provided identity as proof.
- Transactional, restart-safe worker with explicit adapter interface and durable receipts.
- Safe reconciliation state machine and operator tooling; no automatic replay of ambiguous effects.
- Real local Next.js → FastAPI → PostgreSQL/pgvector → approval → workflow → synthetic receipt tests, including kill/restart, concurrent claims, invalidated approval, duplicate requests, and failed adapters.
- Security review, no committed secrets, and a complete clean-start Docker run.

No paid infrastructure or public deployment is permitted before these gates pass.
