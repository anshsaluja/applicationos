# ApplicationOS Architecture

## Core principle
ApplicationOS is an approval-gated agentic workflow system, not a chatbot. PostgreSQL is the source of truth for workspaces, source documents, requirements, evidence, dependencies, approvals, action state, and execution history. Text extracted from a document is **untrusted input**, never proof that a requirement is satisfied or authorization to perform an action.

## Local-first topology (required before deployment)
- **Next.js / React / TypeScript:** application dashboard. Production flows must call the real FastAPI service; mocked browser tests are only isolated UI regressions.
- **FastAPI:** validates bounded uploads, manages workspaces and requirement/evidence state, enforces authenticated approvals, and exposes auditable workflow status.
- **PostgreSQL + pgvector:** durable relational state and optional similarity search. Use migrations, unique constraints, transactions, and concurrency tests rather than relying on in-memory state.
- **LangGraph worker (in progress):** durable checkpoints, explicit retry budgets, worker leases/claiming, interruption recovery, and deterministic synthetic action adapters.
- **Docker Compose:** disposable local database and services for reproducible integration and end-to-end tests. No paid services or external credentials are required.

## Trust boundaries and workflow
1. Upload PDF/text with strict byte/page/time/resource limits, validated MIME/content, sanitized metadata, content hashes, and source offsets/excerpts. Reject malformed or excessive input.
2. Extract normalized requirements with exact document provenance. Build dependency edges and record ambiguous or unsupported assertions for review.
3. Attach evidence to requirements; verification must distinguish missing, pending, verified, blocked, and inconsistent, with a reason and supporting source.
4. Propose an action and persist its intent. Approval must bind an authenticated actor to the **specific action and payload version**; rejection is terminal unless explicitly replanned.
5. Revalidate approval and authorization **at execution time**. Claim work atomically with worker ownership and lease expiration.
6. Use stable idempotency keys and transactional intent/outbox records to avoid duplicate consequential effects across retries or crashes. Do not claim exactly-once execution without a cooperating idempotent downstream adapter.
7. Persist checkpoints, attempts, errors, and outcomes; surface them in the UI. Test worker crashes before/after claims and before/after synthetic effects.

## Safety and observability
- Default-deny consequential actions. Synthetic adapters only for local tests and demos; no real emails, payments, or submissions.
- Uploaded content must not alter system instructions, approval policy, tool permissions, or secrets.
- Keep secrets out of source, test fixtures, logs, and client bundles; use environment variables and example placeholders.
- Emit structured logs with correlation/workflow IDs, redacted payloads, state transitions, retry counts, and terminal errors.
- Evaluation fixtures must catch hallucinated requirements, unsupported evidence matches, duplicate ingestion, stale approvals, and recovery-induced duplicate actions.

## Future deployment (not part of local completion)
S3, SQS, AWS, Kubernetes/EKS, and hosted observability are **optional future architectures**, not currently required or approved infrastructure. Never provision paid resources. Evaluate Netlify/Render/Neon free-tier suitability only **after** the clean-start local document → requirement → evidence → approval → execution journey and CI/E2E release gates pass. Free-tier availability and limits must be checked before any deployment.

## Verification status
This document describes intended boundaries, **not evidence that every component is implemented**. The complete real-stack local end-to-end journey and durable external execution remain unverified. See [ROADMAP.md](../ROADMAP.md) for release gates.
