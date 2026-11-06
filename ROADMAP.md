# ApplicationOS Roadmap

## Release policy

**No fixed public-demo deadline.** Complete and verify the product locally before attempting hosting. Work on `dev`; promote only tested, stable checkpoints to `main`. Keep total infrastructure spend at **$0** and never commit credentials.

## Definition of done

A clean local checkout can start the full stack and complete a real, reproducible synthetic apartment-application journey:

1. Upload bounded PDF/text instructions and supporting evidence, preserving source identity, excerpts, and provenance.
2. Extract and persist reviewable requirements and their dependencies without treating instructions as proof of satisfaction.
3. Link and verify evidence, showing missing, pending, verified, and inconsistent states with traceable reasons.
4. Prepare a durable workflow, require authenticated human approval, and execute only explicitly permitted actions.
5. Recover safely from worker interruption and retries without duplicating consequential actions.
6. Inspect the workflow timeline, evidence, approvals, errors, and outcomes through a polished, responsive Next.js interface backed by the real FastAPI service.

## Engineering workstreams

### Persistence and document intelligence
- PostgreSQL/pgvector schema, migrations, restart persistence, and integration tests.
- Safe PDF/text parsing with size and resource bounds, sanitized metadata, and source provenance.
- Requirement extraction, dependency graph, state transitions, and evidence verification.
- Hallucination/evidence regression fixtures: unsupported claims must remain unverified.

### Durable, approval-gated orchestration
- LangGraph nodes and persisted checkpoints.
- Worker ownership/leases, retry budgets, idempotency, interruption recovery, and safe terminal states.
- Operator identity, auditable approvals/rejections, and authorization rechecks immediately before consequential actions.
- No external side effects in tests or demos; use synthetic adapters.

### Product experience
- Complete Next.js → FastAPI integration for uploads, requirements, evidence, approvals, and workflow history.
- Responsive, accessible interface with intentional empty/loading/error/success states.
- No placeholder buttons or mocked API data presented as production functionality.

### Verification and release gates
- Ruff, PyTest, PostgreSQL/pgvector integration tests, TypeScript check, and Next.js production build pass.
- Playwright covers the **real** frontend/backend/database journey; mocked browser tests alone are insufficient.
- Docker-based clean-start smoke test, restart/recovery tests, and reproducible synthetic fixtures pass.
- Secrets review, security hygiene, logging/observability, architecture and demo documentation complete.
- Only then evaluate free-tier Netlify/Render/Neon hosting and perform public smoke tests; no paid provisioning.

## Status discipline

A committed test is not a passing test. A passing mocked browser test is not an integrated end-to-end test. Report implementation, verified checks, remaining blockers, and deployment separately. Completion percentages are estimates, not substitutes for the release gates above.
