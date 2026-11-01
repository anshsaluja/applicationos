# ApplicationOS

ApplicationOS is an agentic AI platform that turns complex application requirements, documents, deadlines, and follow-up tasks into an executable workflow.

Instead of acting like a generic chatbot, ApplicationOS maintains durable workflow state: requirements, supporting evidence, dependencies, inconsistencies, deadlines, proposed actions, approvals, and execution history.

## What it will do

A user creates an application workspace, uploads instructions and supporting documents, and ApplicationOS:

1. extracts structured requirements from unstructured source material,
2. builds a dependency-aware requirement graph,
3. links evidence from uploaded documents to each requirement,
4. detects missing, blocked, or inconsistent requirements,
5. proposes the next best actions,
6. requires human approval before consequential external actions,
7. updates the workflow as new evidence or actions arrive.

The first polished demo workflow will model an apartment application, while the underlying system is designed to generalize to other application processes.

## Stack

- Python + FastAPI
- LangGraph
- PostgreSQL + pgvector
- Next.js + React + TypeScript
- Docker / Docker Compose
- AWS S3 + SQS
- Kubernetes / EKS-ready manifests
- GitHub Actions
- PyTest + Playwright
- OpenTelemetry / CloudWatch

## Architecture

ApplicationOS separates the synchronous API from long-running agent and document-processing work. Uploaded artifacts are persisted in object storage, durable workflow state lives in PostgreSQL, and asynchronous jobs are processed by agent workers. The agent layer performs extraction, planning, verification, and action preparation while preserving source-level evidence and requiring approval gates for external actions.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the system design and [`ROADMAP.md`](ROADMAP.md) for the MVP plan.

## Current status

Active development. Target: deployed, tested, portfolio-ready MVP by November 15, 2026.
