# Local release security gates

This checklist is not evidence that any gate passed. ApplicationOS remains local-only until executable evidence is recorded.

## Trust boundaries

- Uploaded PDFs and text are untrusted data. Embedded instructions must never override application policy, approve actions, or access tools.
- Resolve reviewer identity from authenticated server-side sessions, never from a caller-provided reviewer_id. Enforce workspace membership and deny by default.
- Preserve provenance: source document, page or offset, excerpt, and extraction version. Unsupported claims must not be marked verified.
- Persist workflow checkpoint, approval, idempotency key, outbox intent, and execution receipt transactionally. Dispatched does not imply workflow success.
- Disable external effects. Permit only a deterministic synthetic adapter until external idempotency and queryable receipts are independently verified.

## Required executable scenarios (unverified)

| Test | Expected behavior |
| --- | --- |
| PDF prompt injection requests approval bypass | Treated as source text only |
| Malformed, encrypted, oversized PDF | Bounded safe rejection |
| Duplicate upload, extraction, workflow request | Idempotent records; no duplicate effects |
| Cross-workspace read or approval | Denied without leaking data |
| Forged reviewer identity or missing session | Denied and audited |
| Missing evidence excerpt | Unsupported, never verified |
| Revoked approval between claim and confirmation | Fail closed |
| Two workers claim same intent | At most one succeeds |
| Worker killed after claim before receipt | Quarantine; no automatic replay |
| Adapter timeout or uncertain outcome | Quarantine until reconciled |
| API, database, or worker restart | Durable state and no duplicate effect |
| Browser upload to requirement to evidence to approval to synthetic execution | UI, API, database and receipt agree |
| Browser refresh mid-workflow | Backend restores state |
| Logs and error responses | No secrets or document bodies |
| Clean Docker checkout, migration, seed and tests | Repeatable zero-cost local run |

## Evidence required before promotion

Record commit SHA, exact CI run and conclusion, local commands and exit codes, database migration revision, Playwright report, and redacted synthetic workflow ID. A test file's existence or an older green CI result is not proof. Do not promote to main or deploy publicly before these gates pass.

## Immediate priorities

1. Durable synthetic receipts and transactional workflow completion.
2. Real PostgreSQL concurrency, restart and duplicate integration tests.
3. Authenticated, workspace-scoped approvals with negative tests.
4. Document provenance and hallucination checks.
5. Full Next.js to FastAPI to PostgreSQL local Playwright journey.