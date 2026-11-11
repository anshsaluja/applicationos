"""Opt-in durable LangGraph planning with PostgreSQL checkpoints.

This is an advisory planning boundary, not an execution queue. Every action
must still pass transactional approval and idempotency checks in persistence.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy.engine import make_url

from .planning_graph import build_planning_graph


def checkpoint_config(thread_id: UUID | str) -> dict:
    """Use a stable, nonempty action identifier to isolate graph histories."""
    identifier = str(thread_id).strip()
    if not identifier:
        raise ValueError("A stable nonempty thread_id is required")
    return {"configurable": {"thread_id": identifier}}


def checkpoint_dsn(database_url: str) -> str:
    """Normalize a SQLAlchemy PostgreSQL URL for psycopg's checkpoint saver.

    Reject other database dialects instead of accidentally opening a different
    database. Preserve URL-encoded credentials when rendering the connection URL.
    """
    if not database_url or not database_url.strip():
        raise ValueError("PostgreSQL checkpoint DSN is required")
    try:
        url = make_url(database_url.strip())
    except Exception as exc:
        raise ValueError("Invalid PostgreSQL checkpoint DSN") from exc
    if url.drivername not in ("postgresql", "postgresql+psycopg"):
        raise ValueError("PostgreSQL checkpoint DSN must use psycopg")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


@contextmanager
def postgres_planning_graph(database_url: str, *, initialize: bool = False) -> Iterator:
    """Open a durable planner for the lifetime of a database connection.

    Run setup only during an explicit initialization/migration step, not on
    every API request. Reopen this context with the same database and thread
    identifier to inspect or resume saved checkpoints after process restart.

    Note: use a psycopg-compatible PostgreSQL DSN; this helper never sends
    workflow actions or accepts graph state as execution authorization.
    """
    with PostgresSaver.from_conn_string(checkpoint_dsn(database_url)) as saver:
        if initialize:
            saver.setup()
        yield build_planning_graph(checkpointer=saver)
