"""Failure-injection tests for durable planner initialization and cleanup."""

from contextlib import contextmanager

import pytest

from app import durable_planning


def test_failed_checkpoint_setup_closes_connection_without_compiling(monkeypatch):
    events = []

    class FakeSaver:
        @staticmethod
        @contextmanager
        def from_conn_string(dsn):
            events.append("open")
            try:
                yield FakeSaver()
            finally:
                events.append("close")

        def setup(self):
            events.append("setup")
            raise RuntimeError("migration unavailable")

    def compile_graph(*, checkpointer):
        events.append("compile")
        return object()

    monkeypatch.setattr(durable_planning, "PostgresSaver", FakeSaver)
    monkeypatch.setattr(durable_planning, "build_planning_graph", compile_graph)

    with (
        pytest.raises(RuntimeError, match="migration unavailable"),
        durable_planning.postgres_planning_graph(
            "postgresql://localhost/test", initialize=True
        ),
    ):
        pass

    assert events == ["open", "setup", "close"]


def test_checkpoint_connection_closes_on_generator_early_exit(monkeypatch):
    events = []

    class FakeSaver:
        @staticmethod
        @contextmanager
        def from_conn_string(dsn):
            events.append("open")
            try:
                yield object()
            finally:
                events.append("close")

    monkeypatch.setattr(durable_planning, "PostgresSaver", FakeSaver)
    monkeypatch.setattr(
        durable_planning, "build_planning_graph", lambda **kwargs: object()
    )

    with durable_planning.postgres_planning_graph(
        "postgresql://localhost/test"
    ) as graph:
        assert graph is not None

    assert events == ["open", "close"]
