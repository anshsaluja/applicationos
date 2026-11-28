# ApplicationOS

ApplicationOS is an agentic AI platform for turning application documents and instructions into traceable requirements, evidence, and approval-gated workflows. The first demonstration domain is apartment applications.

## Intended user journey

1. Create an application workspace and ingest source documents.
2. Extract requirements with source provenance and build dependencies.
3. Associate supporting evidence; distinguish missing, pending, and verified requirements.
4. Prepare actions with durable state and explicit human approval before consequential execution.
5. Inspect workflow checkpoints, retry history, and outcomes.

**Safety boundary:** An instruction found in an uploaded document is not proof that it was fulfilled. Extracted text must never be treated as authorization to execute an external action.

## Stack

- FastAPI, Python, SQLAlchemy, PostgreSQL and pgvector
- Next.js, React, TypeScript
- LangGraph (workflow integration in progress)
- Docker Compose, GitHub Actions, PyTest, Playwright

AWS, Kubernetes, hosted observability, and public deployment are architectural options, **not prerequisites for local verification**. Do not provision paid services for this project.

## Development and verification

The `dev` branch is the integration branch; promote to `main` only after the corresponding checkpoint is tested. The GitHub Actions workflow runs four independent jobs:

- **api:** installs `apps/api` with dev dependencies, runs Ruff, prepares a pgvector-enabled PostgreSQL schema, then executes PyTest.
- **web:** TypeScript typecheck and Next.js production build.
- **browser:** installs Chromium and runs `npm run test:e2e` in `apps/web` (mocked API coverage).
- **compose-e2e:** boots the disposable PostgreSQL, FastAPI and Next.js stack, exercises the synthetic document-to-approval journey and runs the real-backend Playwright provenance journey.

For a local frontend-only check, run `npm install`, `npx tsc --noEmit`, `npm run build`, and `npm run test:e2e` from `apps/web`. These browser tests currently mock API responses; **a passing browser job is not proof of an integrated backend workflow**.

For API tests, provision a **local** PostgreSQL instance with pgvector, set `DATABASE_URL` to a local test database, install `apps/api` with `pip install -e '.[dev]'`, and run `ruff check .` and `pytest -q` from `apps/api`. Use disposable test data and never point tests at a production database. The CI workflow contains the exact database setup used in GitHub Actions.

## Reproducible release verification (local only)

Use an isolated disposable environment, never a production database. From the repository root:

```sh
docker compose config --quiet
docker compose up -d --wait --wait-timeout 300
curl --fail --silent --show-error http://127.0.0.1:8000/ready
curl --fail --silent --show-error http://127.0.0.1:3000/ >/dev/null
docker compose exec -T postgres psql -U applicationos -d applicationos -v ON_ERROR_STOP=1 -c 'CREATE EXTENSION IF NOT EXISTS vector'
docker compose exec -T api python -c 'from app.persistence import Base, build_engine; engine = build_engine(); Base.metadata.create_all(bind=engine); engine.dispose()'
```

The synthetic HTTP journey requires disposable reviewer credentials; follow the exact `APPLICATIONOS_SMOKE_*` environment setup in `.github/workflows/ci.yml` rather than using real credentials. Run the API test suite and Playwright real-backend journey as defined in that workflow. After verification, stop the stack with `docker compose down` (do **not** add `-v` unless you intend to destroy disposable database volumes). Record the tested SHA, individual CI job conclusions, and any restart/recovery failures before promoting `dev` to `main`.

## Release gate: do not deploy until all are verified

- PDF/text ingestion is safe, bounded, and preserves provenance.
- Requirement graph and evidence states persist correctly in PostgreSQL.
- Durable orchestration, idempotency, retry, recovery, and approval checks survive restarts.
- Real Next.js → FastAPI → PostgreSQL flows work with synthetic documents.
- API, integration, browser, and hallucination/evidence regression checks pass.
- Docker-based clean-start end-to-end journey is reproducible and documented.
- Secrets are absent from commits and logs; deployment can be completed at $0.

**Current verification status:** The CI configuration includes a real-PostgreSQL API smoke journey and a Compose-backed browser journey, but a green historical run is not proof that the current `dev` SHA passes. Independent clean-start local verification and restart/recovery testing remain outstanding. Do not promote or deploy without current-SHA evidence. Public deployment is intentionally deferred; there is no fixed launch deadline.

See [architecture](docs/ARCHITECTURE.md) and [roadmap](ROADMAP.md) for design and scope.
