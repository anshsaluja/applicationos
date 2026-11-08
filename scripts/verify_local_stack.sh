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
python3 scripts/smoke_local_journey.py
echo "Local document-to-review HTTP smoke passed (approval/execution NOT tested)."
