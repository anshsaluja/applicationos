# ApplicationOS Architecture

## Core principle
ApplicationOS is an agentic workflow system, not a chatbot. The source of truth is a persistent application workflow composed of requirements, evidence, dependencies, actions, and approval state.

## High-level flow

1. User creates an application workspace.
2. Instructions and supporting documents are uploaded.
3. The ingestion pipeline extracts text and metadata.
4. The agent workflow converts source material into normalized requirements.
5. Evidence is matched to requirements.
6. Verification marks requirements as satisfied, missing, blocked, or inconsistent.
7. The planner proposes next actions.
8. External or consequential actions require explicit human approval.
9. Approved actions are executed and the workflow is re-evaluated.

## Services

### Web
Next.js + React + TypeScript dashboard.

### API
FastAPI service responsible for workspaces, requirements, uploads, evidence, approvals, and workflow status.

### Agent worker
Python worker running LangGraph workflows for extraction, planning, verification, and action preparation.

### PostgreSQL + pgvector
Stores durable product state, normalized requirements, evidence links, workflow runs, and embeddings.

### S3
Stores source documents and derived artifacts.

### SQS
Queues long-running ingestion and agent jobs in cloud deployments.

## Deployment direction
The API and agent worker are separately containerized. Local development uses Docker Compose. Cloud deployment targets AWS, with S3/SQS managed services and Kubernetes manifests designed to be EKS-ready.

## Safety and trust
- External actions are never silently executed.
- Evidence-backed conclusions retain source references.
- Agent runs are persisted for replay and evaluation.
- Idempotency keys protect repeated jobs/actions.
- Failed workflow nodes expose explicit retry state.
