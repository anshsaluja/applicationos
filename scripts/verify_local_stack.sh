#!/usr/bin/env bash
# Run the real HTTP + PostgreSQL synthetic document-to-review smoke journey.
# No public hosting, paid services, approvals, or external execution.
set -Eeuo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "Docker with Compose v2 is required." >&2
  exit 2
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not running." >&2
  exit 2
fi

# Refuse a remote Docker context: local-only is a deliberate safety boundary.
docker_host="${DOCKER_HOST:-}"
if [[ -n "$docker_host" && "$docker_host" != unix://* && "$docker_host" != npipe://* ]]; then
  echo "Refusing non-local DOCKER_HOST." >&2
  exit 2
fi

# Never disrupt a developer's already-running Compose stack.
existing_services="$(docker compose ps --status running --services)"
if [[ -n "$existing_services" ]]; then
  echo "Refusing to modify running Compose services: $existing_services" >&2
  exit 2
fi
started_stack=0
cleanup() {
  if [[ "$started_stack" -eq 1 ]]; then
    # Preserve volumes and data for inspection; stop only our own stack.
    docker compose down || true
  fi
}
trap cleanup EXIT

docker compose config --quiet
started_stack=1
docker compose up -d --wait --wait-timeout 240 postgres api web
# Docker reports container health, but verify that the browser-facing page is reachable
# from the host as well. This catches incorrect port mappings and startup races.
python3 - <<'PY'
import time
import urllib.error
import urllib.request

for attempt in range(40):
    try:
        with urllib.request.urlopen("http://127.0.0.1:3000", timeout=3) as response:
            body = response.read(256_000).decode("utf-8", errors="replace")
            if response.status == 200 and "ApplicationOS" in body:
                print("Next.js host HTTP readiness: PASS")
                break
    except (urllib.error.URLError, TimeoutError):
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

for attempt in range(40):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/ready", timeout=3) as response:
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
docker compose exec -T postgres psql -U applicationos -d applicationos -v ON_ERROR_STOP=1 \
  -c "CREATE EXTENSION IF NOT EXISTS vector"
docker compose exec -T api python - <<'PY'
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
docker compose exec -T \
  -e APPLICATIONOS_SMOKE_REVIEW_TOKEN= \
  -e APPLICATIONOS_SMOKE_SYNTHETIC_EXECUTION= \
  api python /workspace/scripts/smoke_local_journey.py
docker compose exec -T postgres psql -U applicationos -d applicationos -v ON_ERROR_STOP=1 -Atc \
  "SELECT extname FROM pg_extension WHERE extname = 'vector'" | grep -qx vector
docker compose exec -T postgres psql -U applicationos -d applicationos -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) > 0 FROM documents" | grep -qx t
# A smoke pass is not sufficient if records disappear after the API restarts.
# Capture a specific awaiting-approval checkpoint, not just aggregate row counts.
checkpoint_id="$(docker compose exec -T postgres psql -U applicationos -d applicationos -v ON_ERROR_STOP=1 -Atc \
  "SELECT action_id FROM workflow_checkpoints WHERE status = 'awaiting_approval' ORDER BY action_id DESC LIMIT 1")"
if [[ -z "$checkpoint_id" ]]; then
  echo "No awaiting-approval workflow persisted by smoke test." >&2
  exit 1
fi
documents_before="$(docker compose exec -T postgres psql -U applicationos -d applicationos -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) FROM documents")"
requirements_before="$(docker compose exec -T postgres psql -U applicationos -d applicationos -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) FROM requirements")"
test "$documents_before" -gt 0
test "$requirements_before" -gt 0
docker compose restart api
python3 - <<'PY'
import json
import time
import urllib.error
import urllib.request

for _ in range(60):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/ready", timeout=3) as response:
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

action_id = os.environ["CHECKPOINT_ID"]
with urllib.request.urlopen(
    f"http://127.0.0.1:8000/v1/workflows/{action_id}", timeout=10
) as response:
    workflow = json.load(response)
assert workflow["action_id"] == action_id, "Wrong checkpoint returned after restart"
assert workflow["status"] == "awaiting_approval", "Approval boundary changed after restart"
print("Awaiting-approval checkpoint survived API restart: PASS")
PY
documents_after="$(docker compose exec -T postgres psql -U applicationos -d applicationos -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) FROM documents")"
requirements_after="$(docker compose exec -T postgres psql -U applicationos -d applicationos -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) FROM requirements")"
test "$documents_after" -eq "$documents_before"
test "$requirements_after" -eq "$requirements_before"
echo "Local HTTP, ingestion, provenance, idempotency, approval-boundary persistence and API restart smoke passed (browser and signed approval/execution NOT tested)."
