# ApplicationOS Roadmap

Target: portfolio-ready MVP by November 15, 2026.

## Product goal
Turn unstructured application instructions, emails, and documents into an executable workflow with requirements, evidence, dependencies, deadlines, inconsistencies, and approved next actions.

## MVP milestones

### 1. Foundation
- Monorepo structure for API and web app
- FastAPI backend
- Next.js + TypeScript frontend
- PostgreSQL + pgvector data model
- Docker Compose local environment
- Shared configuration and environment templates

### 2. Document intelligence
- PDF/text upload pipeline
- S3-compatible storage abstraction
- Structured extraction with source citations
- Requirement detection and normalization
- Evidence linking between requirements and documents

### 3. Agentic workflow
- LangGraph state machine
- Planner, extractor, verifier, and action nodes
- Requirement graph with dependencies
- Missing and inconsistent requirement detection
- Human approval gate for external actions
- Retry and failure state handling

### 4. Product experience
- Application dashboard
- Requirement status view
- Evidence/source view
- Workflow timeline
- Action approval UI
- Demo apartment-application workflow

### 5. Cloud and infrastructure
- Docker images for API and worker
- SQS-backed background processing
- S3 document storage
- AWS deployment target
- Kubernetes manifests / EKS-ready deployment
- GitHub Actions CI/CD
- CloudWatch/OpenTelemetry observability

### 6. Quality bar
- PyTest backend suite
- Playwright critical-path tests
- Agent evaluation fixtures
- Failure/retry tests
- README with architecture and demo instructions
- Deployed public demo

## Definition of done
A user can upload application instructions and supporting documents, receive a structured requirement graph, see satisfied/missing/inconsistent requirements with evidence, approve a suggested action, and observe the workflow update end-to-end.
