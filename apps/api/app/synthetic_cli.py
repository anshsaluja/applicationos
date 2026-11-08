"""Explicit, local-only entry point for the synthetic no-op worker.

Usage (from apps/api):
    python -m app.synthetic_cli --max-actions 10

This command does not initialize tables, send network requests, or perform
external actions. It requires an explicit local opt-in to prevent accidental
execution against a hosted database.
"""

from __future__ import annotations

import argparse
import os
from uuid import UUID

from .persistence import build_session_factory
from .synthetic_worker import dispatch_one_synthetic


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local synthetic no-op outbox worker")
    parser.add_argument("--max-actions", type=int, default=1)
    parser.add_argument("--action-id", type=UUID)
    args = parser.parse_args(argv)
    if not 1 <= args.max_actions <= 100:
        parser.error("--max-actions must be between 1 and 100")
    if args.action_id is not None and args.max_actions != 1:
        parser.error("--action-id requires --max-actions 1")
    if os.getenv("APPLICATIONOS_ENABLE_SYNTHETIC_WORKER") != "local-only":
        parser.error("Set APPLICATIONOS_ENABLE_SYNTHETIC_WORKER=local-only to opt in")
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith(("postgresql+psycopg://", "postgresql://")):
        parser.error("Set DATABASE_URL explicitly to a local PostgreSQL database")
    # Avoid accidental writes to cloud PostgreSQL; remote hosts require a
    # separate deliberate operator workflow, which this CLI does not support.
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import ArgumentError

    try:
        parsed = make_url(url)
        host = parsed.host
        _ = parsed.port
    except (ArgumentError, ValueError):
        parser.error("DATABASE_URL is not a valid PostgreSQL connection URL")
    # libpq query parameters can override the URL hostname. Refuse all
    # connection-routing overrides, even when the visible host is local.
    if any(key.lower() in {"host", "hostaddr", "service"} for key in parsed.query):
        parser.error("DATABASE_URL must not override its connection host")
    if host not in {"localhost", "127.0.0.1", "::1", "postgres"}:
        parser.error("Synthetic worker only accepts localhost or Docker postgres host")
    factory = build_session_factory(url)
    count = 0
    for _ in range(args.max_actions):
        receipt = dispatch_one_synthetic(factory, action_id=args.action_id)
        if receipt is None:
            break
        count += 1
        print(f"synthetic receipt action_id={receipt.action_id} adapter={receipt.adapter}")
    print(f"synthetic actions completed: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
