# Local release verification (no deployment)

This is a **manual release gate**, not a claim that a local release has passed. Run it on a developer machine with Docker Engine/Compose, Python 3.12, Node 22, and Chromium support. Use disposable synthetic data only. Never connect this stack to production credentials or a paid provider.

## Clean-start check

1. Check out the exact candidate commit on `dev` and record `git rev-parse HEAD`. Do not test an uncommitted working tree.
2. Inspect `docker compose config` before starting services. Confirm ports and credentials are local-only. The Compose credentials are for development, not production.
3. Start the disposable stack with `docker compose up -d --wait --wait-timeout 300`. Inspect `docker compose ps`; do not proceed if any required service is unhealthy.
4. Enable pgvector with `docker compose exec -T postgres psql -U applicationos -d applicationos -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS vector"`.
5. Initialize the local schema (the API does not automatically migrate it):

   ```sh
   docker compose exec -T api python -c 'from app.persistence import Base, build_engine; engine = build_engine(); Base.metadata.create_all(bind=engine); engine.dispose()'
   ```

6. Check `curl -fsS http://127.0.0.1:8000/ready` and `curl -fsS http://127.0.0.1:3000/`. A healthy API alone does not demonstrate a working browser flow.

## Test the actual integrated journey

- With a disposable local reviewer token configured for the stack, run `docker compose exec -T api python /workspace/scripts/smoke_local_journey.py` using the smoke environment variables documented in `.github/workflows/ci.yml`. Never paste tokens into screenshots or commit logs.
- From `apps/web`, install dependencies and Chromium, then run `APPLICATIONOS_REAL_E2E=1 npm exec playwright test e2e/real-backend.spec.ts` with `APPLICATIONOS_E2E_REVIEW_TOKEN` set to the same disposable review token. A mocked browser suite is **not** a substitute.
- Confirm uploaded document provenance, requirement and evidence association, reviewer approval boundary, persisted workflow status, and a synthetic completion. Rejecting an action must not execute it.
- Record the created workflow action ID and its status. Restart **only** the API using `docker compose restart api`, wait for `/ready`, then fetch that same action ID again. Confirm its status and checkpoint survived; checking only row counts is insufficient.
- Query PostgreSQL to confirm the `vector` extension, document rows, requirement rows, and workflow checkpoints exist. Confirm replaying an already-accepted idempotency key does not create a second consequential action.

## Quality and security gate

- API: from `apps/api`, run `ruff check .` and `pytest -q` with a **disposable local** pgvector database. A passing subset is not a passing suite.
- Web: from `apps/web`, run `npx tsc --noEmit`, `npm run build`, and `npm run test:e2e`. Record exact versions and whether the tests use mocks.
- Check the matching commit's GitHub Actions jobs: API, web, browser, and Compose E2E must all be green. A successful earlier commit does not verify later changes.
- Review document size/type limits, unsafe input rejection, provenance retention, reviewer authentication, approval revocation, retry exhaustion, error/log redaction, and request correlation IDs. Treat any unverified control as an open release blocker.
- Do not claim LangGraph durability, pgvector similarity retrieval, external action delivery, or hosted observability solely because a dependency or table exists. Verify the actual behavior or describe it as incomplete.

## Cleanup and evidence

Capture commit SHA, local command results, CI run URL, browser test report, sanitized logs, and any known gaps in the release notes. Keep synthetic artifacts only; do not publish private document content.

When finished, stop the disposable stack with `docker compose down`. Use `docker compose down -v` **only after confirming** that all local database data can be destroyed. Do not deploy or promote `dev` to `main` until every required gate passes and the checkpoint is reviewed.

**Status:** This checklist is documentation. It does not certify that the local E2E run has been performed.
