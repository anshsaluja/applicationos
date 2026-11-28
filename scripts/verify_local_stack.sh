#!/usr/bin/env bash
# Run the real HTTP + PostgreSQL synthetic document-to-review smoke journey.
# No public hosting, paid services, approvals, or external execution.
set -Eeuo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Verification must use the checked-in stack and its own project identity.
# Ambient Compose overrides could silently start unrelated services, mount
# developer data, or target a different project despite the safety checks below.
for override in \
  COMPOSE_FILE COMPOSE_PROJECT_NAME COMPOSE_PROFILES COMPOSE_ENV_FILES \
  COMPOSE_PATH_SEPARATOR COMPOSE_CONVERT_WINDOWS_PATHS COMPOSE_IGNORE_ORPHANS \
  COMPOSE_REMOVE_ORPHANS COMPOSE_DISABLE_ENV_FILE COMPOSE_PROJECT_DIRECTORY; do
  if [[ -n "${!override:-}" ]]; then
    echo "Refusing ambient $override override during isolated verification." >&2
    exit 2
  fi
done

# Compose can discover these files without an exported COMPOSE_FILE.
for config in .env compose.yaml compose.yml docker-compose.yaml \
  compose.override.yaml compose.override.yml docker-compose.override.yaml docker-compose.override.yml; do
  if [[ -e "$config" || -L "$config" ]]; then
    echo "Refusing implicit Compose configuration: $config. Use a clean checkout." >&2
    exit 2
  fi
done
# This acceptance path never performs signed approvals; do not forward
# ambient reviewer credentials into the temporary API container.
export APPLICATIONOS_REVIEW_TOKEN= APPLICATIONOS_REVIEWER_ID=

compose() {
  docker compose --file "$PWD/docker-compose.yml" "$@"
}

if ! command -v docker >/dev/null 2>&1 || ! compose version >/dev/null 2>&1; then
  echo "Docker with Compose v2 is required." >&2
  exit 2
fi
# Validate the endpoint BEFORE contacting the Docker daemon. Even a read-only
# docker info call can disclose host metadata to a configured remote daemon.
# Explicit DOCKER_HOST overrides the active context in the normal CLI path.
# Reject remote endpoints regardless of which selector is currently active.
# Refuse a remote Docker context: local-only is a deliberate safety boundary.
docker_host="${DOCKER_HOST:-}"
if [[ -n "$docker_host" && "$docker_host" != unix:///* && "$docker_host" != npipe:////./pipe/* ]]; then
  echo "Refusing non-local DOCKER_HOST." >&2
  exit 2
fi

# DOCKER_HOST is not the only way to select a remote daemon: an active
# Docker context can point to SSH or TCP even when DOCKER_HOST is unset.
# Inspect the effective endpoint and refuse remote execution before any writes.
context_host="$(docker context inspect "$(docker context show)" --format '{{.Endpoints.docker.Host}}')"
if [[ "$context_host" != unix:///* && "$context_host" != npipe:////./pipe/* ]]; then
  echo "Refusing non-local Docker context endpoint." >&2
  exit 2
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not running." >&2
  exit 2
fi

# Never disrupt an existing Compose stack, including stopped containers:
# `up` could recreate them or unexpectedly reuse their persisted volumes.
existing_services="$(compose ps --all --services)"
if [[ -n "$existing_services" ]]; then
  echo "Refusing to modify existing Compose services: $existing_services" >&2
  exit 2
fi
# Compose may leave named volumes behind even after all containers are removed.
# Never run a verification journey against potentially developer-owned data.
# Resolve the Compose project name from its validated configuration rather
# than guessing a directory prefix or trusting a caller-provided project name.
compose config --quiet
compose_project="$(compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
if [[ -z "$compose_project" ]]; then
  echo "Unable to determine Compose project name." >&2
  exit 2
fi
existing_volumes="$(docker volume ls --filter "label=com.docker.compose.project=$compose_project" --format '{{.Name}}')"
if [[ -n "$existing_volumes" ]]; then
  echo "Refusing to reuse existing Compose volumes: $existing_volumes" >&2
  exit 2
fi

started_stack=0
cleanup() {
  if [[ "$started_stack" -eq 1 ]]; then
    # Preserve volumes and data for inspection; stop only our own stack.
    compose down || true
  fi
}
trap cleanup EXIT

compose config --quiet
started_stack=1
compose up -d --wait --wait-timeout 240 postgres api web
# Docker reports container health, but verify that the browser-facing page is reachable
# from the host as well. This catches incorrect port mappings and startup races.
python3 - <<'PY'
import time
import urllib.error
import urllib.request

# Never route loopback verification traffic through ambient HTTP(S) proxies.
class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects during localhost-only verification."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Local verification refused HTTP redirect")


opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), NoRedirect
)

for attempt in range(40):
    try:
        with opener.open("http://127.0.0.1:3000", timeout=3) as response:
            body = response.read(256_000).decode("utf-8", errors="replace")
            if response.status == 200 and "ApplicationOS" in body:
                print("Next.js host HTTP readiness: PASS")
                break
    except (urllib.error.URLError, TimeoutError, ValueError):
        pass
    time.sleep(2)
else:
    raise SystemExit("Next.js did not serve the ApplicationOS page on localhost:3000")
PY
# Require actual database-backed readiness before schema and smoke checks.
python3 - <<'PY'
import json
import time
import urllib.error
import urllib.request

# Never route loopback verification traffic through ambient HTTP(S) proxies.
class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects during localhost-only verification."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Local verification refused HTTP redirect")


opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), NoRedirect
)

for attempt in range(40):
    try:
        with opener.open("http://127.0.0.1:8000/ready", timeout=3) as response:
            if response.status == 200 and json.load(response) == {"status": "ready"}:
                print("FastAPI PostgreSQL readiness: PASS")
                break
    except (urllib.error.URLError, TimeoutError, ValueError):
        pass
    time.sleep(2)
else:
    raise SystemExit("FastAPI/PostgreSQL readiness failed on localhost:8000")
PY
# The API intentionally does not create tables at startup. Prepare the local
# database explicitly before testing, just as the CI Compose job does.
compose exec -T postgres psql -U applicationos -d applicationos -v ON_ERROR_STOP=1 \
  -c "CREATE EXTENSION IF NOT EXISTS vector"
compose exec -T api python - <<'PY'
from app.persistence import Base, build_engine

engine = build_engine()
try:
    Base.metadata.create_all(bind=engine)
finally:
    engine.dispose()
PY

# Run inside the API container so the installed dependencies and local
# PostgreSQL hostname match the real service, without host Python setup.
# Approval and synthetic execution remain opt-in; never supply a token here.
smoke_result="$(compose exec -T \
  -e APPLICATIONOS_SMOKE_REVIEW_TOKEN= \
  -e APPLICATIONOS_SMOKE_SYNTHETIC_EXECUTION= \
  api python /workspace/scripts/smoke_local_journey.py)"
# Capture the workflow created by THIS smoke invocation, rather than selecting
# an unrelated older checkpoint from a preserved development database.
checkpoint_id="$(SMOKE_RESULT="$smoke_result" python3 - <<'PY'
import json
import os
import uuid

result = json.loads(os.environ["SMOKE_RESULT"])
assert result["result"] == "PASS", "Smoke journey did not pass"
action_id = result["workflow_id"]
uuid.UUID(action_id)
print(action_id)
PY
)"
printf '%s\n' "$smoke_result"
# Preserve the exact smoke-created document and workspace for post-restart
# HTTP provenance checks, rather than relying on global database row counts.
document_id="$(SMOKE_RESULT="$smoke_result" python3 - <<'PY'
import json
import os
import uuid

result = json.loads(os.environ["SMOKE_RESULT"])
value = result["document_id"]
uuid.UUID(value)
print(value)
PY
)"
workspace_id="$(SMOKE_RESULT="$smoke_result" python3 - <<'PY'
import json
import os
import uuid

result = json.loads(os.environ["SMOKE_RESULT"])
value = result["workspace_id"]
uuid.UUID(value)
print(value)
PY
)"
expected_sha256="$(SMOKE_RESULT="$smoke_result" python3 - <<'PY'
import json
import os

digest = json.loads(os.environ["SMOKE_RESULT"])["document_sha256"]
assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
print(digest)
PY
)"
compose exec -T postgres psql -U applicationos -d applicationos -v ON_ERROR_STOP=1 -Atc \
  "SELECT extname FROM pg_extension WHERE extname = 'vector'" | grep -qx vector
# Check the actual pgvector distance operator, not only extension registration.
compose exec -T postgres psql -U applicationos -d applicationos -v ON_ERROR_STOP=1 -Atc \
  "WITH candidates(id, embedding) AS (VALUES (1, '[1,0,0]'::vector(3)), (2, '[0,1,0]'::vector(3)), (3, '[0,0,1]'::vector(3))) SELECT (SELECT id FROM candidates ORDER BY embedding <-> '[0.9,0.1,0]'::vector(3), id LIMIT 1) = 1 AND abs(('[1,0,0]'::vector(3) <-> '[0,1,0]'::vector(3)) - sqrt(2.0)) < 0.00001" | grep -qx t
compose exec -T postgres psql -U applicationos -d applicationos -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) > 0 FROM documents" | grep -qx t
# A smoke pass is not sufficient if records disappear after the API restarts.
# Capture a specific awaiting-approval checkpoint, not just aggregate row counts.
persisted_checkpoint="$(compose exec -T postgres psql -U applicationos -d applicationos -v ON_ERROR_STOP=1 -Atc \
  "SELECT status FROM workflow_checkpoints WHERE action_id = '$checkpoint_id'")"
test "$persisted_checkpoint" = awaiting_approval
if [[ -z "$checkpoint_id" ]]; then
  echo "No awaiting-approval workflow persisted by smoke test." >&2
  exit 1
fi
documents_before="$(compose exec -T postgres psql -U applicationos -d applicationos -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) FROM documents")"
requirements_before="$(compose exec -T postgres psql -U applicationos -d applicationos -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) FROM requirements")"
test "$documents_before" -gt 0
test "$requirements_before" -gt 0
compose restart api
python3 - <<'PY'
import json
import time
import urllib.error
import urllib.request

# Never route loopback verification traffic through ambient HTTP(S) proxies.
class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects during localhost-only verification."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Local verification refused HTTP redirect")


opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), NoRedirect
)

for _ in range(60):
    try:
        with opener.open("http://127.0.0.1:8000/ready", timeout=3) as response:
            if response.status == 200 and json.load(response) == {"status": "ready"}:
                print("API restart and PostgreSQL readiness: PASS")
                break
    except (urllib.error.URLError, TimeoutError, ValueError):
        pass
    time.sleep(2)
else:
    raise SystemExit("API failed readiness after restart")
PY
# Compare the exact checkpoint via HTTP, not merely its database row.
CHECKPOINT_ID="$checkpoint_id" python3 - <<'PY'
import json
import os
import urllib.request

# Never route loopback verification traffic through ambient HTTP(S) proxies.
class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects during localhost-only verification."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Local verification refused HTTP redirect")


opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), NoRedirect
)

action_id = os.environ["CHECKPOINT_ID"]
with opener.open(
    f"http://127.0.0.1:8000/v1/workflows/{action_id}", timeout=10
) as response:
    workflow = json.load(response)
assert workflow["action_id"] == action_id, "Wrong checkpoint returned after restart"
assert workflow["status"] == "awaiting_approval", "Approval boundary changed after restart"
print("Awaiting-approval checkpoint survived API restart: PASS")
PY
# Verify the exact document, its source links, and its persisted workspace
# remain accessible through FastAPI after the process has restarted.
DOCUMENT_ID="$document_id" WORKSPACE_ID="$workspace_id" EXPECTED_SHA256="$expected_sha256" python3 - <<'PY'
import json
import os
import urllib.request

# Never route loopback verification traffic through ambient HTTP(S) proxies.
class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects during localhost-only verification."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Local verification refused HTTP redirect")


opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), NoRedirect
)

base = "http://127.0.0.1:8000"
document_id = os.environ["DOCUMENT_ID"]
workspace_id = os.environ["WORKSPACE_ID"]

def get(path):
    with opener.open(base + path, timeout=10) as response:
        assert response.status == 200
        return json.load(response)

document = get(f"/v1/documents/{document_id}")
assert document["id"] == document_id, "Smoke document was not restored"
assert document["sha256"] == os.environ["EXPECTED_SHA256"], "Persisted document digest differs from uploaded synthetic bytes"
sources = get(f"/v1/documents/{document_id}/requirement-sources")
assert sources and all(item["source_document_id"] == document_id for item in sources), (
    "Document requirement provenance was lost after restart"
)
requirements = get(f"/v1/workspaces/{workspace_id}/requirements")
assert requirements["workspace_id"] == workspace_id
assert requirements["requirements"], "Persisted requirements missing after restart"
# A nonempty source list and a nonempty workspace are insufficient: prove
# that the exact source candidates remain linked to persisted requirements.
source_requirement_ids = {str(item["requirement_id"]) for item in sources}
stored_requirement_ids = {str(item["id"]) for item in requirements["requirements"]}
assert source_requirement_ids == stored_requirement_ids, (
    "Document source candidates no longer match persisted workspace requirements"
)
assert all(not item["satisfaction_evidence"] for item in sources), (
    "Instruction provenance was incorrectly presented as satisfaction evidence"
)
print("Document provenance and workspace requirements survived API restart: PASS")
PY
# A restart must not weaken the review gate or create a second checkpoint
# when the original idempotency key is replayed.
CHECKPOINT_ID="$checkpoint_id" python3 - <<'PY'
import json
import os
import urllib.error
import urllib.request

# Never route loopback verification traffic through ambient HTTP(S) proxies.
class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects during localhost-only verification."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Local verification refused HTTP redirect")


opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), NoRedirect
)
from uuid import uuid4

base = "http://127.0.0.1:8000"
action_id = os.environ["CHECKPOINT_ID"]

def post(path, body):
    request = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return opener.open(request, timeout=10)

with opener.open(base + f"/v1/workflows/{action_id}", timeout=10) as response:
    original = json.load(response)
key = original["idempotency_key"]
assert key, "Persisted workflow has no idempotency key"

with post("/v1/workflows", {"action_id": action_id, "idempotency_key": key}) as response:
    replay = json.load(response)
assert replay == original, "Restarted API changed checkpoint on idempotent replay"

try:
    with post("/v1/workflows", {
        "action_id": str(uuid4()), "idempotency_key": key,
    }):
        pass
except urllib.error.HTTPError as error:
    assert error.code == 409, f"Conflicting replay returned {error.code}, expected 409"
else:
    raise AssertionError("Restarted API accepted a conflicting idempotency key")

try:
    with post(f"/v1/workflows/{action_id}/decision", {
        "decision": "approved", "reason": "Unauthorized restart regression probe",
    }):
        pass
except urllib.error.HTTPError as error:
    assert error.code == 403, f"Unauthenticated approval returned {error.code}, expected 403"
else:
    raise AssertionError("Restarted API accepted an unauthenticated approval")

with opener.open(base + f"/v1/workflows/{action_id}", timeout=10) as response:
    final = json.load(response)
assert final == original, "Rejected operations mutated awaiting-approval checkpoint"

# A read-only reconciliation check must not invent a dispatched effect or
# synthetic receipt for a workflow that has never been approved.
with opener.open(base + f"/v1/workflows/{action_id}/dispatch-status", timeout=10) as response:
    dispatch = json.load(response)
assert dispatch["action_id"] == action_id
assert dispatch["workflow_status"] == "awaiting_approval"
assert dispatch["outbox_status"] is None, "Unapproved workflow unexpectedly has an outbox intent"
assert dispatch["synthetic_receipt_present"] is False
assert dispatch["synthetic_receipt_valid"] is False
assert dispatch["reconciliation_required"] is False

# A duplicate review request after restart must preserve the same checkpoint,
# including its retry budget, rather than resetting or advancing the workflow.
with post(f"/v1/workflows/{action_id}/request-review", {}) as response:
    repeated_review = json.load(response)
assert repeated_review == original, "Duplicate review changed the durable checkpoint"
print("Restart idempotency, approval and dispatch boundaries: PASS")
PY
# Exercise a real PostgreSQL process restart, not only an API restart.
# A connection pool may hold stale sockets briefly; wait for the API's actual
# database-backed readiness endpoint before asserting durable state.
compose restart postgres
python3 - <<'PY'
import json
import time
import urllib.error
import urllib.request

# Never route loopback verification traffic through ambient HTTP(S) proxies.
class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects during localhost-only verification."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Local verification refused HTTP redirect")


opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), NoRedirect
)
for attempt in range(60):
    try:
        with opener.open("http://127.0.0.1:8000/ready", timeout=3) as response:
            if response.status == 200 and json.load(response) == {"status": "ready"}:
                print("PostgreSQL restart and API database reconnection: PASS")
                break
    except (urllib.error.URLError, TimeoutError, ValueError):
        pass
    time.sleep(2)
else:
    raise SystemExit("API did not recover database-backed readiness after PostgreSQL restart")
PY
CHECKPOINT_ID="$checkpoint_id" python3 - <<'PY'
import json
import os
import urllib.request

# Never route loopback verification traffic through ambient HTTP(S) proxies.
class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects during localhost-only verification."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Local verification refused HTTP redirect")


opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), NoRedirect
)
with opener.open(
    f"http://127.0.0.1:8000/v1/workflows/{os.environ['CHECKPOINT_ID']}",
    timeout=10,
) as response:
    checkpoint = json.load(response)
assert checkpoint["action_id"] == os.environ["CHECKPOINT_ID"]
assert checkpoint["status"] == "awaiting_approval", (
    "PostgreSQL restart lost or advanced an unapproved workflow"
)
print("Approval-gated workflow survived PostgreSQL restart: PASS")
PY
documents_after="$(compose exec -T postgres psql -U applicationos -d applicationos -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) FROM documents")"
requirements_after="$(compose exec -T postgres psql -U applicationos -d applicationos -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) FROM requirements")"
test "$documents_after" -eq "$documents_before"
test "$requirements_after" -eq "$requirements_before"
# PostgreSQL restart must restore working pgvector operators as well as rows.
compose exec -T postgres psql -U applicationos -d applicationos -v ON_ERROR_STOP=1 -Atc \
  "WITH candidates(id, embedding) AS (VALUES (1, '[1,0,0]'::vector(3)), (2, '[0,1,0]'::vector(3)), (3, '[0,0,1]'::vector(3))) SELECT (SELECT id FROM candidates ORDER BY embedding <-> '[0.9,0.1,0]'::vector(3), id LIMIT 1) = 1 AND abs(('[1,0,0]'::vector(3) <-> '[0,1,0]'::vector(3)) - sqrt(2.0)) < 0.00001" | grep -qx t
# Recheck exact document provenance after the PostgreSQL process restart.
DOCUMENT_ID="$document_id" WORKSPACE_ID="$workspace_id" EXPECTED_SHA256="$expected_sha256" python3 - <<'PY'
import json
import os
import urllib.request

# Never route loopback verification traffic through ambient HTTP(S) proxies.
class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects during localhost-only verification."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Local verification refused HTTP redirect")


opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), NoRedirect
)
base = "http://127.0.0.1:8000"
def get(path):
    with opener.open(base + path, timeout=10) as response:
        assert response.status == 200
        return json.load(response)

document_id = os.environ["DOCUMENT_ID"]
workspace_id = os.environ["WORKSPACE_ID"]
document = get(f"/v1/documents/{document_id}")
assert document["id"] == document_id
assert document["sha256"] == os.environ["EXPECTED_SHA256"], "Persisted document digest differs from uploaded synthetic bytes"
sources = get(f"/v1/documents/{document_id}/requirement-sources")
requirements = get(f"/v1/workspaces/{workspace_id}/requirements")
assert requirements["workspace_id"] == workspace_id
assert sources, "PostgreSQL restart lost source links"
assert all(source["source_document_id"] == document_id for source in sources)
assert {str(source["requirement_id"]) for source in sources} == {
    str(requirement["id"]) for requirement in requirements["requirements"]
}, "PostgreSQL restart changed requirement provenance"
assert all(not source["satisfaction_evidence"] for source in sources)
print("PostgreSQL restart exact document provenance: PASS")
PY
# Recheck authorization and idempotency *after the database restart*, when
# SQLAlchemy may have replaced pooled connections. A successful GET alone
# does not establish that the approval boundary survived reconnection.
CHECKPOINT_ID="$checkpoint_id" python3 - <<'PY'
import json
import os
import urllib.error
import urllib.request

# Never route loopback verification traffic through ambient HTTP(S) proxies.
class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects during localhost-only verification."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Local verification refused HTTP redirect")


opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), NoRedirect
)
from uuid import uuid4

base = "http://127.0.0.1:8000"
action_id = os.environ["CHECKPOINT_ID"]

def get(path):
    with opener.open(base + path, timeout=10) as response:
        return json.load(response)

def post(path, body):
    request = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return opener.open(request, timeout=10)

original = get(f"/v1/workflows/{action_id}")
assert original["status"] == "awaiting_approval"
key = original["idempotency_key"]
assert key, "Missing persisted idempotency key after PostgreSQL restart"
with post("/v1/workflows", {"action_id": action_id, "idempotency_key": key}) as response:
    assert json.load(response) == original, "PostgreSQL restart changed replay result"

for path, body, expected in (
    ("/v1/workflows", {"action_id": str(uuid4()), "idempotency_key": key}, 409),
    (f"/v1/workflows/{action_id}/decision", {"decision": "approved", "reason": "Unauthorized database restart probe"}, 403),
):
    try:
        with post(path, body):
            pass
    except urllib.error.HTTPError as error:
        assert error.code == expected, f"{path}: expected {expected}, got {error.code}"
    else:
        raise AssertionError(f"{path} unexpectedly accepted a forbidden mutation")

assert get(f"/v1/workflows/{action_id}") == original, (
    "Rejected requests mutated the checkpoint after PostgreSQL restart"
)
dispatch = get(f"/v1/workflows/{action_id}/dispatch-status")
assert dispatch["action_id"] == action_id, "PostgreSQL restart returned dispatch status for a different workflow"
assert dispatch["workflow_status"] == "awaiting_approval"
assert dispatch["outbox_status"] is None
assert dispatch["synthetic_receipt_present"] is False
assert dispatch["synthetic_receipt_valid"] is False
assert dispatch["reconciliation_required"] is False
# A repeated review transition must remain a no-op after the database pool
# reconnects; otherwise a restart could silently reset the approval gate.
with post(f"/v1/workflows/{action_id}/request-review", {}) as response:
    assert json.load(response) == original, (
        "PostgreSQL restart changed checkpoint on duplicate review request"
    )
assert get(f"/v1/workflows/{action_id}") == original, (
    "Duplicate review mutated the checkpoint after PostgreSQL restart"
)
# Re-read dispatch state after the duplicate review, not just the checkpoint.
# A regression could enqueue an outbox intent without changing the checkpoint.
assert get(f"/v1/workflows/{action_id}/dispatch-status") == dispatch, (
    "Duplicate review changed dispatch state after PostgreSQL restart"
)
print("PostgreSQL restart idempotency and authorization boundaries: PASS")
PY
echo "Local HTTP, ingestion, exact SHA-256 provenance, idempotency, approval boundary, API and PostgreSQL restart authorization checks passed (browser and signed approval/execution NOT tested)."
