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

cleanup() {
  # Preserve the named database volume for debugging; do not delete user data.
  docker compose down --remove-orphans || true
}
trap cleanup EXIT

docker compose config --quiet
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
python3 scripts/smoke_local_journey.py
echo "Local Next.js HTTP readiness and document-to-review API smoke passed (browser interactions and approval/execution NOT tested)."
