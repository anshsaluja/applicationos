"""Opt-in durable LangGraph planning with PostgreSQL checkpoints.

This is an advisory planning boundary, not an execution queue. Every action
must still pass transactional approval and idempotency checks in persistence.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from uuid import UUID

from langgraph.checkpoint.postgres import PostgresSaver

from .planning_graph import build_planning_graph


def checkpoint_config(thread_id: UUID | str) -> dict:
    """Use a stable, nonempty action identifier to isolate graph histories."""
    identifier = str(thread_id).strip()
    if not identifier:
        raise ValueError("A stable nonempty thread_id is required")
    return {"configurable": {"thread_id": identifier}}


@contextmanager
def postgres_planning_graph(database_url: str, *, initialize: bool = False) -> Iterator:
    """Open a durable planner for the lifetime of a database connection.

    Run setup only during an explicit initialization/migration step, not on
    every API request. Reopen this context with the same database and thread
    identifier to inspect or resume saved checkpoints after process restart.

    Note: use a psycopg-compatible PostgreSQL DSN; this helper never sends
    workflow actions or accepts graph state as execution authorization.
    """
    if not database_url or not database_url.strip():
        raise ValueError("PostgreSQL checkpoint DSN is required")
    with PostgresSaver.from_conn_string(database_url) as saver:
        if initialize:
            saver.setup()
        yield build_planning_graph(checkpointer=saver)
